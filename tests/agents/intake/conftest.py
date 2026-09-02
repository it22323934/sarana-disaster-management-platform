"""Fakes for the intake agent's six ports.

The interesting ones are the gazetteer and the duplicate index, because the claims worth
testing are about what the agent does when those answer ambiguously: a landmark that matches
two divisions, and a neighbour whose similarity lands in the band nobody can resolve.

Everything records what it was asked. Several claims here are about what the agent *did not*
do - did not merge, did not produce a point, did not keep an unsupported count - and a test
can only assert that against something that remembers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_svc.agents.intake.ports import (
    IntakeOutcome,
    NeighbourReport,
    Place,
    Transcript,
)

# A fixed instant during Ditwah's landfall night, so every timestamp in these tests is
# relative to something real rather than to whenever the suite happened to run.
NOW = datetime(2026, 11, 28, 4, 0, tzinfo=UTC)

DIVISION = "LK-21-01-001"
OTHER_DIVISION = "LK-21-01-002"

# Gampola, Kandy district. Inside Sri Lanka, inside the seeded divisions.
GAMPOLA_LON = 80.5714
GAMPOLA_LAT = 7.1642


@dataclass
class FakeGazetteer:
    """Place lookups, with ambiguity as a first-class configuration."""

    places: dict[str, list[Place]] = field(default_factory=dict)
    division_at: str | None = DIVISION
    lookups: list[str] = field(default_factory=list)

    async def lookup(self, name: str, *, near_division: str | None = None) -> list[Place]:
        self.lookups.append(name)
        return list(self.places.get(name.lower(), []))

    async def division_for(self, lon: float, lat: float) -> str | None:
        return self.division_at


@dataclass
class FakeStore:
    """Where the enrichment lands, and what incident a report became."""

    transcripts: dict[str, Transcript] = field(default_factory=dict)
    embeddings: dict[str, list[float]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    next_incident: str = "inc-1"

    async def save_transcript(self, report_id: str, transcript: Transcript) -> None:
        self.transcripts[report_id] = transcript

    async def save_embedding(self, report_id: str, embedding: list[float], model: str) -> None:
        self.embeddings[report_id] = embedding

    async def link_or_create(self, report_id: str, **kwargs: Any) -> IntakeOutcome:
        self.calls.append({"report_id": report_id, **kwargs})
        link = kwargs.get("link_to_incident")
        incident = link or self.next_incident
        return IntakeOutcome(
            report_id=report_id,
            incident_id=incident,
            public_ref=f"INC-261128-{incident.upper()}",
            linked_to=link,
            created=link is None,
        )


@dataclass
class FakeIndex:
    """The kNN search. Returns whatever a test configured, most similar first."""

    candidates: list[NeighbourReport] = field(default_factory=list)
    queried: int = 0

    async def neighbours(self, embedding: list[float], **kwargs: Any) -> list[NeighbourReport]:
        self.queried += 1
        return sorted(self.candidates, key=lambda candidate: -candidate.similarity)


@dataclass
class FakeEmbedder:
    """A deterministic stand-in for a multilingual embedding model.

    Returns a fixed vector: the agent never inspects it, and the similarity that drives
    every dedup decision is supplied by `FakeIndex` instead. Embedding for real in a unit
    test would measure the provider, not the agent.
    """

    calls: list[str] = field(default_factory=list)

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1] * 8


@dataclass
class FakeTranscriber:
    """ASR, with confidence as the interesting dial."""

    transcript: Transcript | None = None
    fails: bool = False
    hints: list[str] = field(default_factory=list)

    async def transcribe(
        self, audio_uri: str, *, language_hints: tuple[str, ...], keyword_context: str
    ) -> Transcript:
        self.hints.append(keyword_context)
        if self.fails:
            raise ConnectionError("the ASR provider is unreachable")
        return self.transcript or Transcript(
            text_original="transcribed",
            text_en="transcribed",
            detected_language="si",
            confidence=0.9,
            provider="fake",
            model="fake-asr",
        )


@dataclass
class FakeTranslator:
    """Sinhala or Tamil in, a marked English string out."""

    fails: bool = False

    async def to_english(self, text: str, *, source_language: str) -> str:
        if self.fails:
            raise ConnectionError("the translation provider is unreachable")
        return f"[en of {source_language}] {text}"


class RecordingCall:
    """A model stand-in answering with a fixed string, remembering the prompts."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


class BrokenCall:
    """A model provider that is down. Every agent must work without one."""

    async def __call__(self, prompt: str) -> str:
        raise ConnectionError("the model provider is unreachable")


def place(name: str, division: str = DIVISION, *, lon: float = GAMPOLA_LON) -> Place:
    return Place(
        name=name,
        gn_division_code=division,
        lon=lon,
        lat=GAMPOLA_LAT,
        accuracy_m=500.0,
    )


def neighbour(
    report_id: str,
    *,
    similarity: float,
    incident_id: str | None = "inc-existing",
    minutes_ago: int = 4,
    text_original: str = "",
    text_en: str = "",
    incident_type: str = "STRUCTURAL_COLLAPSE",
    division: str = DIVISION,
) -> NeighbourReport:
    return NeighbourReport(
        report_id=report_id,
        incident_id=incident_id,
        gn_division_code=division,
        incident_type=incident_type,
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        similarity=similarity,
        text_original=text_original,
        text_en=text_en,
    )


def report_input(
    *,
    report_id: str = "rep-1",
    text: str | None = None,
    audio: str | None = None,
    lon: float | None = None,
    lat: float | None = None,
    accuracy_m: float | None = None,
    source: str | None = None,
    channel: str = "SMS",
    division: str | None = None,
) -> dict[str, Any]:
    """The `output` dict a run starts with."""
    return {
        "report_id": report_id,
        "channel": channel,
        "received_at": NOW.isoformat(),
        "correlation_id": "test-correlation",
        "raw_text": text,
        "raw_audio_uri": audio,
        "lon": lon,
        "lat": lat,
        "location_accuracy_m": accuracy_m,
        "location_source": source,
        "sender_gn_division_code": division,
    }


@pytest.fixture
def gazetteer() -> FakeGazetteer:
    return FakeGazetteer(places={"gampola": [place("Gampola")]})


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def index() -> FakeIndex:
    return FakeIndex()
