"""What the intake graph needs from the outside world, as narrow protocols.

Six ports. The agent has to run end to end against fakes, because the claims it makes are
claims a test has to be able to hold it to: that a Tamil voice note and a Sinhala SMS about
one collapsed house become one incident, that two genuinely different reports do not, that
an ambiguous landmark produces a division and no point, and that 200 reports clear p95 in
under 45 seconds. None of those can be tested against an ASR provider, an embedding API and
a live Postgres.

## Nothing here is a coordinate the model produced

`Gazetteer` is a lookup, always. `Transcriber` returns text. `ModelCall` returns text. There
is deliberately no port through which a model can hand this agent a latitude and longitude -
it will confidently produce plausible, wrong ones, and a wrong coordinate on a dispatch map
sends a crew to the wrong village.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RawReport:
    """One report as it arrived, before this agent touched it.

    A projection of `incident.raw_report`. `raw_audio_uri` is a reference, never the audio:
    a checkpoint holds references rather than blobs, and base64 audio in a checkpoint row
    makes every resume slow and every debugging session miserable.
    """

    report_id: str
    channel: str
    received_at: datetime
    correlation_id: str = ""

    raw_text: str | None = None
    raw_audio_uri: str | None = None
    reported_language: str | None = None

    lon: float | None = None
    lat: float | None = None
    location_accuracy_m: float | None = None
    location_source: str | None = None

    # The division the sender is believed to be in, if anything already knows. Used to
    # build the ASR keyword hints and to bound the duplicate search; never used as the
    # report's location, which is `geolocate`'s job.
    sender_gn_division_code: str | None = None

    @property
    def has_audio(self) -> bool:
        return bool(self.raw_audio_uri)

    @property
    def has_coordinate(self) -> bool:
        return self.lon is not None and self.lat is not None


@dataclass(frozen=True, slots=True)
class Transcript:
    """What the ASR produced, and how much it should be trusted.

    `text_original` is the record and `text_en` is a working artefact. Build file 15 is
    explicit about which is which: the English pivot exists so the rest of the pipeline has
    one language to reason in, and the original is what a reviewer reads and what is kept
    permanently.
    """

    text_original: str
    text_en: str | None = None
    detected_language: str | None = None
    confidence: float = 0.0
    provider: str = ""
    model: str = ""


@dataclass(frozen=True, slots=True)
class Place:
    """One gazetteer entry: a name, where it is, and how precisely that is known.

    `accuracy_m` is wide for a landmark on purpose. A village name resolves to a centroid,
    and presenting that with a fifteen-metre radius would put a false precision on a map a
    dispatcher reads under pressure.
    """

    name: str
    gn_division_code: str
    lon: float
    lat: float
    accuracy_m: float
    kind: str = "landmark"


@dataclass(frozen=True, slots=True)
class NeighbourReport:
    """A report already in the system that might be the same event.

    Carries both texts because the LLM adjudication reads both in their original languages -
    a Tamil voice note and a Sinhala SMS about one collapsed house have to be comparable
    without either being translated into the other.
    """

    report_id: str
    incident_id: str | None
    gn_division_code: str
    incident_type: str
    occurred_at: datetime
    similarity: float
    text_original: str = ""
    text_en: str = ""
    lon: float | None = None
    lat: float | None = None


@dataclass(frozen=True, slots=True)
class IntakeOutcome:
    """What one report became."""

    report_id: str
    incident_id: str | None = None
    public_ref: str | None = None
    linked_to: str | None = None
    created: bool = False
    flagged_pairs: list[str] = field(default_factory=list)


class Transcriber(Protocol):
    """Audio in, text out.

    Raises rather than returning an empty transcript when the provider is unreachable. A
    voice note that silently becomes an empty report is one nobody reads and nobody knows
    to look for; the graph catches the failure and queues the audio for a human, which is a
    visible state with a person attached to it.
    """

    async def transcribe(
        self, audio_uri: str, *, language_hints: tuple[str, ...], keyword_context: str
    ) -> Transcript: ...


class Translator(Protocol):
    """Sinhala or Tamil in, English out, original always retained.

    Separate from `Transcriber` because a text SMS needs translating and never needs
    transcribing, and folding them together would make every SMS carry an audio code path.
    """

    async def to_english(self, text: str, *, source_language: str) -> str: ...


class Gazetteer(Protocol):
    """Place names to coordinates. The only thing in this agent that produces a point."""

    async def lookup(self, name: str, *, near_division: str | None = None) -> list[Place]:
        """Every place matching this name, best first.

        Several matches is the interesting answer, not a failure: Sri Lanka has more than
        one Mahawewa, and a landmark that matches three places resolves to a division
        rather than to whichever one sorted first.
        """
        ...

    async def division_for(self, lon: float, lat: float) -> str | None:
        """Which GN division contains this coordinate, or None if it is outside them all."""
        ...


class Embedder(Protocol):
    """Text to a vector, for the duplicate search.

    Multilingual by requirement, not by preference: the recall stage has to match a Tamil
    voice note against a Sinhala SMS about the same collapsed house, and an embedding that
    only works in English would silently never find that pair.
    """

    async def embed(self, text: str) -> list[float]: ...


class DuplicateIndex(Protocol):
    """The kNN search over reports already received."""

    async def neighbours(
        self,
        embedding: list[float],
        *,
        gn_division_code: str,
        since: datetime,
        limit: int,
    ) -> list[NeighbourReport]:
        """Candidate duplicates, most similar first.

        Bounded to one division and one time window by the caller rather than searched
        nationally: a report from Jaffna is not a duplicate of one from Galle, and scanning
        every open report on every intake is how the busiest hour becomes the slowest one.
        """
        ...


class ReportStore(Protocol):
    """Where the enrichment is written, and where an incident is linked or created."""

    async def save_transcript(self, report_id: str, transcript: Transcript) -> None: ...

    async def save_embedding(self, report_id: str, embedding: list[float], model: str) -> None: ...

    async def link_or_create(
        self,
        report_id: str,
        *,
        incident_type: str,
        gn_division_code: str,
        lon: float | None,
        lat: float | None,
        accuracy_m: float | None,
        location_source: str | None,
        people_at_risk: int | None,
        link_to_incident: str | None,
        summary: dict[str, str] | None,
    ) -> IntakeOutcome:
        """Attach this report to an incident, existing or new.

        One call rather than a create and a link, because the choice between them is made
        from the same facts and splitting it would let a report exist attached to nothing
        between two statements.
        """
        ...


class ModelCall(Protocol):
    """One model call: a prompt in, text out.

    The same shape the forecast and warning agents use. Narrow on purpose: a port that
    exposed the client would make every degraded-path test construct one.
    """

    async def __call__(self, prompt: str) -> str: ...
