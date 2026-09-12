"""`python -m agent_svc.agents.intake.bench` - the 45-second latency gate from build file 15.

```bash
python -m agent_svc.agents.intake.bench --reports 200 --assert-p95 45
```

Runs N reports through the real graph concurrently and reports the latency distribution per
stage and end to end. Exits non-zero when p95 is above the asserted budget, so CI fails on a
regression rather than filing a number nobody opens.

## What this measures, and the part it cannot

It measures **the agent's own work**: routing, extraction, geolocation, plausibility, the
duplicate decision, and the graph machinery around them - against in-process fakes for the
providers. That is the part this repository can regress and the part a code change breaks.

It does **not** measure the providers. Transcription is 5-25 seconds of build file 15's
45-second budget and it is somebody else's network call; simulating it with a sleep would
produce a number that says whatever the sleep says. So the fakes here return instantly, the
report set is text-only by default, and the figure this prints is the *floor*: the latency
the platform adds on top of whatever the providers cost.

A run that fails this gate is definitely too slow. A run that passes it is not thereby
proven to meet the 45-second budget in production - that needs the real providers, and
`HANDOFF.md` says so rather than letting the green tick imply it.

`--audio-share` mixes in reports that take the transcription branch, with a configurable
simulated provider latency, for when somebody does want to model the whole budget. It is off
by default because a benchmark whose headline number is a sleep constant is a benchmark that
measures the constant.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from agent_svc.agents.intake import graph as intake
from agent_svc.agents.intake.ports import (
    IntakeOutcome,
    NeighbourReport,
    Place,
    Transcript,
)
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.state import initial_state

DEFAULT_REPORTS: Final = 200
DEFAULT_P95_BUDGET_S: Final = 45.0

# How many run concurrently. Two hundred reports arriving at once is the shape of a real
# surge - a district gets a warning and everybody texts - and running them serially would
# measure a queue nobody has rather than the contention that actually exists.
DEFAULT_CONCURRENCY: Final = 50

DIVISION: Final = "LK-21-01-001"
GAMPOLA: Final = (80.5714, 7.1642)

# The report set. Trilingual on purpose: a benchmark over English-only text would miss that
# the lexicon scans three languages' worth of terms on every report.
SAMPLE_REPORTS: Final[tuple[str, ...]] = (
    "ගම්පොල ප්‍රදේශයේ ගංවතුර. උදව් අවශ්‍යයි.",
    "வீடு இடிந்து விழுந்தது. இரண்டு குழந்தை உள்ளே.",
    "Our house collapsed in Gampola, two children trapped inside, help us now",
    "නායයෑමක් සිදුවී ඇත. මාර්ගය වසා ඇත.",
    "தண்ணீர் வீட்டிற்குள் வருகிறது. உதவி தேவை.",
    "Water rising fast near the bridge, we need to evacuate",
    "ආහාර සහ බීමට වතුර අවශ්‍යයි",
    "My grandmother cannot walk and the water is at the door",
)


@dataclass
class _Gazetteer:
    async def lookup(self, name: str, *, near_division: str | None = None) -> list[Place]:
        return [
            Place(
                name=name,
                gn_division_code=DIVISION,
                lon=GAMPOLA[0],
                lat=GAMPOLA[1],
                accuracy_m=500.0,
            )
        ]

    async def division_for(self, lon: float, lat: float) -> str | None:
        return DIVISION


@dataclass
class _Store:
    written: int = 0

    async def save_transcript(self, report_id: str, transcript: Transcript) -> None:
        return None

    async def save_embedding(self, report_id: str, embedding: list[float], model: str) -> None:
        return None

    async def link_or_create(self, report_id: str, **kwargs: Any) -> IntakeOutcome:
        self.written += 1
        return IntakeOutcome(
            report_id=report_id,
            incident_id=f"inc-{report_id}",
            public_ref=f"INC-261128-{self.written:06d}",
            created=True,
        )


@dataclass
class _Index:
    """Returns a plausible number of candidates so the dedup path is actually exercised.

    An index that returned nothing would benchmark a branch the real system rarely takes.
    """

    per_report: int = 3

    async def neighbours(self, embedding: list[float], **kwargs: Any) -> list[NeighbourReport]:
        now = datetime.now(UTC)
        return [
            NeighbourReport(
                report_id=f"prior-{index}",
                incident_id=f"inc-prior-{index}",
                gn_division_code=DIVISION,
                incident_type="FLOOD",
                occurred_at=now - timedelta(minutes=5 + index),
                # Below the ambiguous band, so no model call is made and the benchmark
                # measures the platform rather than a stubbed adjudication.
                similarity=0.5 + index * 0.05,
                text_en="water in the house",
            )
            for index in range(self.per_report)
        ]


@dataclass
class _Embedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1] * 8


@dataclass
class _Transcriber:
    """A stand-in ASR with a configurable, explicit latency.

    Zero by default. A benchmark whose headline number is dominated by a sleep constant is
    one that measures the constant, so the simulated cost has to be asked for.
    """

    latency_s: float = 0.0

    async def transcribe(
        self, audio_uri: str, *, language_hints: tuple[str, ...], keyword_context: str
    ) -> Transcript:
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        return Transcript(
            text_original=SAMPLE_REPORTS[0],
            text_en="a house collapsed in Gampola",
            detected_language="si",
            confidence=0.92,
            provider="bench",
            model="gpt-transcribe",
        )


@dataclass
class Result:
    """One report's end-to-end latency, and whether it needed a person."""

    report_id: str
    seconds: float
    reviewed: bool
    error: str | None = None


@dataclass
class Report:
    """The distribution, and the verdict."""

    results: list[Result] = field(default_factory=list)
    budget_s: float = DEFAULT_P95_BUDGET_S

    def quantile(self, fraction: float) -> float:
        values = sorted(result.seconds for result in self.results)
        if not values:
            return 0.0
        # Nearest-rank rather than interpolation: with a couple of hundred runs,
        # interpolating invents a number between two real ones.
        index = min(len(values) - 1, max(0, round(fraction * len(values)) - 1))
        return values[index]

    @property
    def errors(self) -> list[Result]:
        return [result for result in self.results if result.error]

    @property
    def reviewed(self) -> int:
        return sum(1 for result in self.results if result.reviewed)

    @property
    def passed(self) -> bool:
        return self.quantile(0.95) <= self.budget_s and not self.errors

    def render(self) -> str:
        lines = [
            f"intake bench: {len(self.results)} reports",
            f"  p50      {self.quantile(0.50) * 1000:8.1f} ms",
            f"  p95      {self.quantile(0.95) * 1000:8.1f} ms   (budget "
            f"{self.budget_s * 1000:.0f} ms)",
            f"  p99      {self.quantile(0.99) * 1000:8.1f} ms",
            f"  max      {self.quantile(1.00) * 1000:8.1f} ms",
            f"  mean     {statistics.fmean(r.seconds for r in self.results) * 1000:8.1f} ms"
            if self.results
            else "  mean          n/a",
            f"  routed to a person: {self.reviewed} of {len(self.results)}",
            "",
            "This is the latency the platform adds, measured against in-process fakes.",
            "It does not include the ASR, translation or embedding providers - see the",
            "module docstring for why simulating them would measure the simulation.",
        ]
        if self.errors:
            lines += ["", f"{len(self.errors)} report(s) failed:"]
            lines += [f"  {result.report_id}: {result.error}" for result in self.errors]
        return "\n".join(lines)


async def _run_one(graph: Any, index: int, *, audio: bool) -> Result:
    """One report through the real graph, timed end to end."""
    report_id = f"bench-{index:05d}"
    state = initial_state(
        agent="intake",
        subject_type="report",
        subject_id=report_id,
        correlation_id=f"bench-{index}",
    )
    state["output"] = {
        "report_id": report_id,
        "channel": "IVR" if audio else "SMS",
        "received_at": datetime.now(UTC).isoformat(),
        "raw_text": None if audio else SAMPLE_REPORTS[index % len(SAMPLE_REPORTS)],
        "raw_audio_uri": f"s3://bench/{report_id}.ogg" if audio else None,
        "lon": GAMPOLA[0],
        "lat": GAMPOLA[1],
        "location_accuracy_m": 20.0,
        "location_source": "gps",
        "sender_gn_division_code": DIVISION,
    }

    started = time.perf_counter()
    try:
        values = await graph.ainvoke(state, config_for(f"intake:report:{report_id}"))
    except Exception as error:  # noqa: BLE001 - a crashed report is a failed one, not a lost one
        return Result(
            report_id=report_id,
            seconds=time.perf_counter() - started,
            reviewed=False,
            error=f"{type(error).__name__}: {error}",
        )

    # The clock covers the pause. A run waiting on a person is not fast: from the outside
    # it is a decision nobody has made, and stopping the timer at the interrupt would make
    # every report the agent could not handle look like the quickest ones.
    return Result(
        report_id=report_id,
        seconds=time.perf_counter() - started,
        reviewed=bool(values.get("__interrupt__")),
    )


async def bench(
    *,
    reports: int = DEFAULT_REPORTS,
    concurrency: int = DEFAULT_CONCURRENCY,
    budget_s: float = DEFAULT_P95_BUDGET_S,
    audio_share: float = 0.0,
    asr_latency_s: float = 0.0,
) -> Report:
    """Run the benchmark. One compiled graph, shared, as the service does it."""
    graph = intake.build(
        memory_checkpointer(),
        gazetteer=_Gazetteer(),
        store=_Store(),
        index=_Index(),
        embedder=_Embedder(),
        transcriber=_Transcriber(latency_s=asr_latency_s) if audio_share > 0 else None,
        division_names={DIVISION: ["Gampola", "Deltota"]},
    )

    audio_every = int(1 / audio_share) if audio_share > 0 else 0
    limit = asyncio.Semaphore(concurrency)

    async def guarded(index: int) -> Result:
        async with limit:
            return await _run_one(
                graph, index, audio=bool(audio_every) and index % audio_every == 0
            )

    results = await asyncio.gather(*(guarded(index) for index in range(reports)))
    return Report(results=list(results), budget_s=budget_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent_svc.agents.intake.bench",
        description="Run N reports through the intake graph and check the p95 latency.",
    )
    parser.add_argument("--reports", type=int, default=DEFAULT_REPORTS)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument(
        "--assert-p95",
        type=float,
        default=DEFAULT_P95_BUDGET_S,
        help="Budget in seconds. Build file 15 sets 45.",
    )
    parser.add_argument(
        "--audio-share",
        type=float,
        default=0.0,
        help="Fraction of reports that take the transcription branch. Off by default.",
    )
    parser.add_argument(
        "--asr-latency",
        type=float,
        default=0.0,
        help="Simulated ASR latency in seconds. See the module docstring before using it.",
    )
    args = parser.parse_args(argv)

    report = asyncio.run(
        bench(
            reports=args.reports,
            concurrency=args.concurrency,
            budget_s=args.assert_p95,
            audio_share=args.audio_share,
            asr_latency_s=args.asr_latency,
        )
    )

    sys.stdout.write(report.render() + "\n")
    if not report.passed:
        sys.stderr.write(
            f"\nFAIL: p95 {report.quantile(0.95):.2f}s is above the {args.assert_p95:.0f}s budget\n"
            if report.quantile(0.95) > args.assert_p95
            else f"\nFAIL: {len(report.errors)} report(s) errored\n"
        )
        return 1

    sys.stdout.write(f"\nPASS: p95 {report.quantile(0.95):.3f}s within {args.assert_p95:.0f}s\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
