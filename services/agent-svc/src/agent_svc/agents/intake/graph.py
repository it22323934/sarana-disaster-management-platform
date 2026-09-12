r"""The incident intake and verification agent.

```
START -> receive_report -> transcribe -> detect_language -> translate -> extract
      -> geolocate -> plausibility -> embed_and_dedup -> [human_review] -> link_or_create
      -> record -> END
```

Eleven nodes and one interrupt. During Ditwah, FloodSupport volunteers phoned each request
to verify it, for more than 300,000 people. This agent is the replacement for that phone
call, and the bar is that it has to be at least as trustworthy as a volunteer with a phone.
That is a high bar and worth saying plainly, because most of the decisions below are about
refusing to do something a volunteer would not have done.

## What a volunteer would not do, and neither does this

**Invent a number.** `people_at_risk` drives triage rank directly, and every count carries
the words from the report that justified it. A count whose evidence is not in the source is
stripped and the report goes to a person - see `extraction.enforce_basis`.

**Invent a place.** No model in this agent can return a coordinate. Geocoding is a gazetteer
lookup, and an ambiguous landmark produces a GN division with no point rather than one of
three equally plausible pins - see `geolocate`.

**Quietly fold one family's emergency into another's.** Every uncertain duplicate decision
produces two incidents and a flagged pair, never one incident - see `dedup`.

**Throw away something that looked odd.** Plausibility flags; it never rejects. The cost of
ignoring a real report because it looked implausible is a death. The cost of a human
spending twenty seconds on a false one is twenty seconds.

## The latency budget is 45 seconds and the shape of it matters

Transcription dominates and everything else is small. `extract` and `embed_and_dedup` are
the two model-bearing stages after it; a text-only SMS skips transcription entirely and
lands well under fifteen seconds. `bench.py` measures p95 against recorded fixtures.

## The degraded path is the path the tests run

With no provider: transcription is unavailable and the report queues as
`audio_pending_transcription`, playable by a reviewer and still dispatchable on its GPS;
extraction falls back to keyword matching over the trilingual lexicon; dedup falls back to
vector similarity alone with everything ambiguous flagged rather than merged. Slower, fully
functional, clearly labelled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final

import structlog
from langgraph.graph import END, START, StateGraph

from agent_svc.agents.intake import dedup as dedup_rules
from agent_svc.agents.intake import extraction, geolocate, lexicon, plausibility
from agent_svc.agents.intake.ports import (
    DuplicateIndex,
    Embedder,
    Gazetteer,
    ModelCall,
    RawReport,
    ReportStore,
    Transcriber,
    Transcript,
    Translator,
)
from agent_svc.runtime.nodes import audit_write, request_approval, rg_append
from agent_svc.runtime.registry import AgentSpec
from agent_svc.runtime.state import AgentState
from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

AGENT: Final = "intake"
SUBJECT_TYPE: Final = "report"

# Below this, the run stops and a person looks at it. The platform's ordinary threshold -
# an agent that reviewed at a different bar from every other one would be quietly more
# permissive without anybody choosing that.
REVIEW_THRESHOLD: Final = 0.70

# Below this an ASR result is never acted on. Build file 15 starts it at 0.75, above the
# ordinary review threshold, because a mis-heard transcript is not a low-confidence answer -
# it is a confident answer to a different question, and the extraction downstream cannot
# tell.
TRANSCRIPTION_THRESHOLD: Final = 0.75

# The processing state a report sits in when the ASR could not be reached. A real state in
# `incident.raw_report.processing_status`, playable by a reviewer in the console.
AUDIO_PENDING: Final = "audio_pending_transcription"

# The embedding model. One place, so a change is one edit and the stored `model` column
# always says which vectors are comparable with which.
EMBEDDING_MODEL: Final = "text-embedding-3-large"


class IntakeState(AgentState, total=False):
    """The intake run's own state, on top of the shared base.

    **Nothing here identifies a person.** No name, no phone number, no exact coordinate for
    a household beyond what the report itself carries, and never the audio. Checkpoints
    outlive the run, are read during debugging, and go to a trace exporter that leaves the
    country (ADR-011).

    The report text does travel, and that is a deliberate exception: it is what a reviewer
    reads in the approval inbox, and an intake agent whose checkpoints did not carry the
    report would produce a review queue nobody could action.
    """

    report: dict[str, Any]
    transcript: dict[str, Any]
    languages: list[str]
    text_original: str
    text_en: str

    extracted: dict[str, Any]
    location: dict[str, Any]
    plausibility: dict[str, Any]
    duplicates: dict[str, Any]

    outcome: dict[str, Any]
    stage_ms: Annotated[dict[str, float], lambda left, right: {**left, **right}]


def build_nodes(
    *,
    gazetteer: Gazetteer,
    store: ReportStore,
    index: DuplicateIndex,
    embedder: Embedder | None = None,
    transcriber: Transcriber | None = None,
    translator: Translator | None = None,
    call: ModelCall | None = None,
    now: datetime | None = None,
    division_names: dict[str, list[str]] | None = None,
    audit: Any = None,
    graph_writer: Any = None,
) -> dict[str, Any]:
    """Build the eleven nodes, closed over their dependencies.

    `transcriber`, `translator`, `embedder` and `call` are all optional and every one of
    them absent is a supported configuration - that is the degraded path, and it is the
    configuration every test in this agent runs under unless it says otherwise.
    """
    names = division_names or {}

    def clock() -> datetime:
        return now if now is not None else utc_now()

    async def receive_report(state: IntakeState) -> dict[str, Any]:
        """Take the report as it arrived. Nothing here can fail."""
        raw = dict(state.get("output", {}))
        report = _as_report(raw, subject_id=str(state.get("subject_id", "")))

        _log.info(
            "intake_report_received",
            report_id=report.report_id,
            channel=report.channel,
            has_audio=report.has_audio,
            has_coordinate=report.has_coordinate,
        )
        return {
            "report": _report_as_dict(report),
            "text_original": report.raw_text or "",
            "notes": [f"report received on {report.channel}"],
        }

    async def transcribe(state: IntakeState) -> dict[str, Any]:
        """Audio only. A text report passes straight through.

        The keyword hints are built from the sender's likely division: the division name,
        its neighbours, and the standing trilingual hazard vocabulary. Build file 15 calls
        this the single highest-leverage accuracy improvement available and it costs
        nothing - a transcriber told that "Gampola" and "නායයෑම" are likely words is
        dramatically better at hearing them in a bad phone recording.
        """
        report = _as_report(state.get("report", {}), subject_id="")
        if not report.has_audio:
            return {}

        if transcriber is None:
            # No ASR. The report is not lost and it is not silently empty: it queues in a
            # state a reviewer can play, and a voice note with a GPS fix is actionable with
            # no transcript at all.
            _log.warning(
                "intake_transcriber_unavailable",
                report_id=report.report_id,
                impact="queued as audio_pending_transcription; still dispatchable on its "
                "coordinate and channel metadata",
            )
            return {
                "transcript": {"status": AUDIO_PENDING},
                "notes": ["no transcriber; the audio is queued for a human to play"],
            }

        hints = lexicon.keyword_context(names.get(report.sender_gn_division_code or "", []))
        try:
            result = await transcriber.transcribe(
                str(report.raw_audio_uri),
                language_hints=("si", "ta", "en"),
                keyword_context=hints,
            )
        except Exception as error:  # noqa: BLE001 - a voice note is never lost to an outage
            _log.error(
                "intake_transcription_failed",
                report_id=report.report_id,
                error=type(error).__name__,
                impact="queued as audio_pending_transcription for a human to play",
            )
            return {
                "transcript": {"status": AUDIO_PENDING, "error": type(error).__name__},
                "notes": ["transcription failed; the audio is queued for a human"],
            }

        low = result.confidence < TRANSCRIPTION_THRESHOLD
        if low:
            # Never auto-published into a life-safety decision. The reviewer gets the audio,
            # the transcript and the extraction side by side.
            _log.info(
                "intake_transcription_low_confidence",
                report_id=report.report_id,
                confidence=result.confidence,
                language=result.detected_language,
                threshold=TRANSCRIPTION_THRESHOLD,
            )

        await store.save_transcript(report.report_id, result)
        return {
            "transcript": _transcript_as_dict(result, low_confidence=low),
            "text_original": result.text_original,
            "text_en": result.text_en or "",
            "notes": [f"transcribed {result.detected_language or '?'} at {result.confidence:.2f}"],
        }

    async def detect_language(state: IntakeState) -> dict[str, Any]:
        """Which languages this report is in. A script test, not a model call.

        Sinhala and Tamil occupy disjoint Unicode blocks, so this is exact and instant.
        See `lexicon.detect` for why the answer is a mix rather than a winner.
        """
        text = state.get("text_original", "") or state.get("text_en", "")
        mix = lexicon.detect(text)

        if mix.code_switched:
            # Code-switching is normal here and it is the hardest input this platform
            # receives. It is also what upgrades the model tier - see `runtime.models`.
            _log.info(
                "intake_code_switched_report",
                languages=list(mix.languages),
                shares={code: round(share, 2) for code, share in mix.shares.items()},
            )

        return {
            "languages": list(mix.languages),
            "notes": [f"language: {mix.primary} ({mix.confidence:.2f})"],
        }

    async def translate(state: IntakeState) -> dict[str, Any]:
        """Produce the English pivot. The original is always kept.

        The English text is a working artefact - one language for the rest of the pipeline
        to reason in. The original is the record, and it is what a reviewer reads.
        """
        if state.get("text_en"):
            return {}

        original = state.get("text_original", "")
        languages = state.get("languages", [])
        primary = languages[0] if languages else "en"

        if primary == "en" or not original:
            return {"text_en": original}

        if translator is None:
            # No translator. The pipeline works on the original: `lexicon` matches Sinhala
            # and Tamil directly, so extraction still functions - which is the whole reason
            # the lexicon is trilingual rather than an English keyword list.
            _log.info(
                "intake_translator_unavailable",
                primary=primary,
                impact="extraction runs on the original text against the trilingual lexicon",
            )
            return {"text_en": ""}

        try:
            english = await translator.to_english(original, source_language=primary)
        except Exception as error:  # noqa: BLE001 - the original is always enough to proceed
            _log.warning(
                "intake_translation_failed",
                error=type(error).__name__,
                impact="extraction runs on the original text against the trilingual lexicon",
            )
            return {"text_en": ""}

        return {"text_en": english, "notes": [f"translated from {primary}"]}

    async def extract(state: IntakeState) -> dict[str, Any]:
        """Pull out the structured facts, and refuse any count the report does not support."""
        original = state.get("text_original", "")
        english = state.get("text_en", "")
        working = english or original

        if not working.strip():
            # An audio report with no transcript, or a bare GPS ping. Not an error: it is
            # dispatchable on its coordinate, and a person reads it.
            unknown = extraction.ExtractedReport(
                incident_type="OTHER",
                confidence=0.0,
                reasoning="this report carries no text to extract from",
                needs_human_review=True,
                review_reason="no text; a person reads the audio or places it from the map",
                provenance="DETERMINISTIC",
            )
            return {"extracted": unknown.model_dump(mode="json")}

        result = await extraction.extract(working, call=call, original_text=original)
        _log.info(
            "intake_report_extracted",
            incident_type=result.incident_type,
            people_at_risk=result.people_at_risk,
            immediate_danger=result.immediate_danger,
            confidence=result.confidence,
            provenance=result.provenance,
        )
        return {
            "extracted": result.model_dump(mode="json"),
            "notes": [f"extracted {result.incident_type} ({result.provenance})"],
        }

    async def locate(state: IntakeState) -> dict[str, Any]:
        """Where the report is. A gazetteer lookup, never a model's coordinate."""
        report = _as_report(state.get("report", {}), subject_id="")
        extracted = dict(state.get("extracted", {}))
        landmarks = [str(name) for name in extracted.get("landmarks", [])]

        located = await geolocate.resolve(report, landmarks=landmarks, gazetteer=gazetteer)
        _log.info(
            "intake_report_located",
            report_id=report.report_id,
            division=located.gn_division_code,
            has_point=located.has_point,
            source=located.source,
        )
        return {
            "location": {
                "gn_division_code": located.gn_division_code,
                "lon": located.lon,
                "lat": located.lat,
                "accuracy_m": located.accuracy_m,
                "source": located.source,
                "basis": located.basis,
                "confidence": located.confidence,
            },
            "notes": [located.as_sentence()],
        }

    async def check_plausibility(state: IntakeState) -> dict[str, Any]:
        """Deterministic checks. Flags, never rejects."""
        report = _as_report(state.get("report", {}), subject_id="")
        extracted = dict(state.get("extracted", {}))
        location = dict(state.get("location", {}))

        verdict = plausibility.check(
            report,
            people_at_risk=extracted.get("people_at_risk"),
            gn_division_code=location.get("gn_division_code"),
            lon=location.get("lon"),
            lat=location.get("lat"),
            now=clock(),
        )
        if verdict.flags:
            _log.info(
                "intake_report_flagged",
                report_id=report.report_id,
                flags=[flag.code for flag in verdict.flags],
                impact="routed to a person; a flag is never a rejection",
            )
        return {"plausibility": verdict.as_dict(), "notes": [verdict.as_sentence()]}

    async def embed_and_dedup(state: IntakeState) -> dict[str, Any]:
        """Find the reports this might duplicate, and decide - biased toward saying no."""
        report = _as_report(state.get("report", {}), subject_id="")
        location = dict(state.get("location", {}))
        division = location.get("gn_division_code")

        if embedder is None or not division:
            # No embedder, or nowhere to search. Not a failure: `incident_svc.domain.dedup`
            # still flags same-division-same-type-nearby pairs deterministically on the
            # write path, and nothing here merges anything without it.
            return {"duplicates": {"considered": 0, "link_to_incident": None, "flagged_pairs": []}}

        working = state.get("text_en", "") or state.get("text_original", "")
        if not working.strip():
            return {"duplicates": {"considered": 0, "link_to_incident": None, "flagged_pairs": []}}

        try:
            vector = await embedder.embed(working)
        except Exception as error:  # noqa: BLE001 - no embedding means no merge, which is safe
            _log.warning(
                "intake_embedding_failed",
                error=type(error).__name__,
                impact="no semantic duplicate search ran; nothing was merged",
            )
            return {"duplicates": {"considered": 0, "link_to_incident": None, "flagged_pairs": []}}

        await store.save_embedding(report.report_id, vector, EMBEDDING_MODEL)
        neighbours = await index.neighbours(
            vector,
            gn_division_code=str(division),
            since=dedup_rules.window_start(clock()),
            limit=dedup_rules.CANDIDATE_LIMIT,
        )

        decision = await dedup_rules.decide(
            incoming_text=state.get("text_en", "") or working,
            incoming_original=state.get("text_original", ""),
            occurred_at=report.received_at,
            neighbours=neighbours,
            call=call,
        )
        return {"duplicates": decision.as_dict(), "notes": [f"{decision.considered} candidates"]}

    async def human_review(state: IntakeState) -> dict[str, Any]:
        """Pause for a person when nothing downstream should act on this unread.

        **This node re-executes from the top when the run resumes.** Everything above the
        `interrupt()` runs a second time, so nothing above it may have a side effect that
        is not idempotent - and there is deliberately nothing above it here but reading
        state. `link_or_create` is a separate node downstream, which is what stops one
        report producing two incidents.
        """
        extracted = dict(state.get("extracted", {}))
        transcript = dict(state.get("transcript", {}))
        location = dict(state.get("location", {}))

        decision = request_approval(
            state,
            question="This report could not be processed confidently. What is it?",
            detail={
                # The audio, the transcript and the extraction side by side, which is what
                # build file 15 asks the reviewer to be shown.
                "audio_uri": state.get("report", {}).get("raw_audio_uri"),
                "transcript_status": transcript.get("status"),
                "transcript_confidence": transcript.get("confidence"),
                "text_original": state.get("text_original", "")[:1000],
                "text_en": state.get("text_en", "")[:1000],
                "suggested_type": extracted.get("incident_type"),
                "people_at_risk": extracted.get("people_at_risk"),
                "people_at_risk_basis": extracted.get("people_at_risk_basis"),
                "division": location.get("gn_division_code"),
                "has_point": location.get("lon") is not None,
                "flags": state.get("plausibility", {}).get("flags", []),
                "duplicate_of": state.get("duplicates", {}).get("flagged_pairs", []),
                "why": extracted.get("review_reason"),
            },
        )

        # Below the interrupt. Runs exactly once.
        confirmed = {
            **extracted,
            "incident_type": decision.get("incident_type", extracted.get("incident_type")),
            "provenance": "HUMAN",
            "needs_human_review": False,
            "review_reason": None,
        }
        if "people_at_risk" in decision:
            confirmed["people_at_risk"] = decision["people_at_risk"]
            confirmed["people_at_risk_basis"] = "confirmed by a reviewer"

        _log.info(
            "intake_report_reviewed",
            decided_by=str(decision.get("decided_by")),
            incident_type=confirmed["incident_type"],
        )
        return {
            "human_decision": decision,
            "extracted": confirmed,
            "notes": [f"{decision.get('decided_by', 'a person')} confirmed this report"],
        }

    async def link_or_create(state: IntakeState) -> dict[str, Any]:
        """Attach the report to an incident, existing or new.

        Downstream of the interrupt, so it runs once however many times `human_review`
        re-executed. One report producing two incidents is the failure this placement
        prevents.
        """
        report = _as_report(state.get("report", {}), subject_id="")
        extracted = dict(state.get("extracted", {}))
        location = dict(state.get("location", {}))
        duplicates = dict(state.get("duplicates", {}))

        division = location.get("gn_division_code")
        if not division:
            # Unplaced. The report is durable and visible; it is not dispatchable until a
            # person places it, and saying so is better than attaching it to a division
            # nobody has evidence for.
            return {
                "outcome": {"report_id": report.report_id, "placed": False, "incident_id": None},
                "notes": ["unplaced; no incident created"],
            }

        outcome = await store.link_or_create(
            report.report_id,
            incident_type=str(extracted.get("incident_type", "OTHER")),
            gn_division_code=str(division),
            lon=location.get("lon"),
            lat=location.get("lat"),
            accuracy_m=location.get("accuracy_m"),
            location_source=location.get("source"),
            people_at_risk=extracted.get("people_at_risk"),
            link_to_incident=duplicates.get("link_to_incident"),
            summary=SUMMARY_NOT_WRITTEN,
        )

        _log.info(
            "intake_incident_resolved",
            report_id=report.report_id,
            incident_id=outcome.incident_id,
            created=outcome.created,
            linked_to=outcome.linked_to,
        )
        return {
            "outcome": {
                "report_id": outcome.report_id,
                "incident_id": outcome.incident_id,
                "public_ref": outcome.public_ref,
                "created": outcome.created,
                "linked_to": outcome.linked_to,
                "placed": True,
            },
            "notes": [
                f"{'created' if outcome.created else 'linked to'} incident "
                f"{outcome.public_ref or outcome.incident_id}"
            ],
        }

    async def record(state: IntakeState) -> dict[str, Any]:
        """Append the observation, write the audit entry, and finish."""
        extracted = dict(state.get("extracted", {}))
        outcome = dict(state.get("outcome", {}))
        location = dict(state.get("location", {}))

        observations = []
        if outcome.get("incident_id") and location.get("gn_division_code"):
            observations.append(
                {
                    "subject_type": "gn_division",
                    "subject_id": location["gn_division_code"],
                    "observation": "incident_reported",
                    "value": extracted.get("incident_type", "OTHER"),
                    "confidence": float(extracted.get("confidence", 0.0)),
                    "source": f"{AGENT}:{extracted.get('provenance', 'DETERMINISTIC')}",
                }
            )
        await rg_append(state, observations=observations, writer=graph_writer)

        audited = await audit_write(
            state,
            action="intake.report.processed",
            subject=str(state.get("report", {}).get("report_id", "")),
            detail={
                "incident_type": extracted.get("incident_type"),
                "provenance": extracted.get("provenance"),
                "people_at_risk": extracted.get("people_at_risk"),
                "division": location.get("gn_division_code"),
                "has_point": location.get("lon") is not None,
                "location_source": location.get("source"),
                "incident_id": outcome.get("incident_id"),
                "linked_to": outcome.get("linked_to"),
                "flagged_pairs": state.get("duplicates", {}).get("flagged_pairs", []),
                "flags": state.get("plausibility", {}).get("flags", []),
                "reviewed_by": (state.get("human_decision") or {}).get("decided_by"),
            },
            writer=audit,
        )

        return {
            **audited,
            "status": "COMPLETED",
            "output": {
                "report_id": state.get("report", {}).get("report_id"),
                "incident_id": outcome.get("incident_id"),
                "public_ref": outcome.get("public_ref"),
                "incident_type": extracted.get("incident_type"),
                "people_at_risk": extracted.get("people_at_risk"),
                "gn_division_code": location.get("gn_division_code"),
                "has_point": location.get("lon") is not None,
                "location_source": location.get("source"),
                "placed": bool(outcome.get("placed")),
                "linked_to": outcome.get("linked_to"),
                "created": bool(outcome.get("created")),
                "flagged_pairs": state.get("duplicates", {}).get("flagged_pairs", []),
                "flags": state.get("plausibility", {}).get("flags", []),
                "confidence": float(extracted.get("confidence", 0.0)),
                "reasoning": str(extracted.get("reasoning", "")),
                "needs_human_review": False,
                "provenance": extracted.get("provenance", "DETERMINISTIC"),
            },
        }

    return {
        "receive_report": receive_report,
        "transcribe": transcribe,
        "detect_language": detect_language,
        "translate": translate,
        "extract": extract,
        "geolocate": locate,
        "plausibility": check_plausibility,
        "embed_and_dedup": embed_and_dedup,
        "human_review": human_review,
        "link_or_create": link_or_create,
        "record": record,
    }


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _as_report(raw: dict[str, Any], *, subject_id: str) -> RawReport:
    """One report, from the run input or from state."""
    received = raw.get("received_at")
    return RawReport(
        report_id=str(raw.get("report_id") or subject_id),
        channel=str(raw.get("channel", "SMS")),
        received_at=(
            datetime.fromisoformat(received) if isinstance(received, str) else received or utc_now()
        ),
        correlation_id=str(raw.get("correlation_id", "")),
        raw_text=raw.get("raw_text"),
        raw_audio_uri=raw.get("raw_audio_uri"),
        reported_language=raw.get("reported_language"),
        lon=raw.get("lon"),
        lat=raw.get("lat"),
        location_accuracy_m=raw.get("location_accuracy_m"),
        location_source=raw.get("location_source"),
        sender_gn_division_code=raw.get("sender_gn_division_code"),
    )


def _report_as_dict(report: RawReport) -> dict[str, Any]:
    return {
        "report_id": report.report_id,
        "channel": report.channel,
        "received_at": report.received_at.isoformat(),
        "correlation_id": report.correlation_id,
        "raw_text": report.raw_text,
        "raw_audio_uri": report.raw_audio_uri,
        "reported_language": report.reported_language,
        "lon": report.lon,
        "lat": report.lat,
        "location_accuracy_m": report.location_accuracy_m,
        "location_source": report.location_source,
        "sender_gn_division_code": report.sender_gn_division_code,
    }


def _transcript_as_dict(transcript: Transcript, *, low_confidence: bool) -> dict[str, Any]:
    """The transcript as it travels in state.

    The text is carried because a reviewer reads it. The audio never is - a checkpoint holds
    references, and base64 audio in a checkpoint row makes every resume slow.
    """
    return {
        "status": "transcribed",
        "detected_language": transcript.detected_language,
        "confidence": transcript.confidence,
        "provider": transcript.provider,
        "model": transcript.model,
        "low_confidence": low_confidence,
    }


# `incident.incident.summary` is a localised JSONB column with a CHECK requiring all three
# languages, and this agent writes **nothing** into it - the same choice
# `incident_svc.service.intake` already made, for the same reason.
#
# A summary is citizen-facing text, and the platform's rule is that no citizen-facing record
# exists in fewer than three languages. This agent has a report in one language and no
# reviewed translation of it, so the only summaries it could produce are a model-written
# sentence nobody checked, or the same original-language excerpt copied into all three
# fields and labelled as Sinhala, Tamil and English. The first is prose about somebody's
# emergency that no native speaker signed; the second is a lie about what the record
# contains.
#
# So the column stays null, the incident is identified by its type and its division, and a
# person writes a summary if one is needed. The type is already trilingual in the console
# through the taxonomy labels.
SUMMARY_NOT_WRITTEN: Final[dict[str, str] | None] = None


# ---------------------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------------------


def needs_person(state: IntakeState) -> bool:
    """Whether this report must not be acted on unread.

    Four independent reasons, and each is a case where proceeding would produce a record
    that looks decided and is not:

      the extraction asked for a person, or was not confident enough;
      the transcription was below its own, higher threshold;
      a plausibility check flagged something;
      a duplicate pair could not be resolved either way.
    """
    extracted = dict(state.get("extracted", {}))
    if extracted.get("needs_human_review"):
        return True
    if float(extracted.get("confidence", 0.0)) < REVIEW_THRESHOLD:
        return True

    transcript = dict(state.get("transcript", {}))
    if transcript.get("low_confidence") or transcript.get("status") == AUDIO_PENDING:
        return True

    if state.get("plausibility", {}).get("flags"):
        return True

    return bool(state.get("duplicates", {}).get("flagged_pairs"))


def _after_dedup(state: IntakeState) -> str:
    return "human_review" if needs_person(state) else "link_or_create"


def build(
    checkpointer: Any,
    *,
    gazetteer: Gazetteer | None = None,
    store: ReportStore | None = None,
    index: DuplicateIndex | None = None,
    embedder: Embedder | None = None,
    transcriber: Transcriber | None = None,
    translator: Translator | None = None,
    call: ModelCall | None = None,
    now: datetime | None = None,
    division_names: dict[str, list[str]] | None = None,
    audit: Any = None,
    graph_writer: Any = None,
) -> Any:
    """Compile the graph.

    `gazetteer`, `store` and `index` are the three that cannot be absent - without them the
    agent cannot place a report, cannot record one, and cannot see a duplicate. A graph
    built without them refuses at the node that needs one rather than completing a run that
    quietly processed nothing.

    Everything else absent is the degraded path, which is a supported configuration and the
    one the tests run.
    """
    nodes = build_nodes(
        gazetteer=gazetteer or _RefusingGazetteer(),
        store=store or _RefusingStore(),
        index=index or _EmptyIndex(),
        embedder=embedder,
        transcriber=transcriber,
        translator=translator,
        call=call,
        now=now,
        division_names=division_names,
        audit=audit,
        graph_writer=graph_writer,
    )

    builder = StateGraph(IntakeState)
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, "receive_report")
    builder.add_edge("receive_report", "transcribe")
    builder.add_edge("transcribe", "detect_language")
    builder.add_edge("detect_language", "translate")
    builder.add_edge("translate", "extract")
    builder.add_edge("extract", "geolocate")
    builder.add_edge("geolocate", "plausibility")
    builder.add_edge("plausibility", "embed_and_dedup")
    builder.add_conditional_edges(
        "embed_and_dedup",
        _after_dedup,
        {"human_review": "human_review", "link_or_create": "link_or_create"},
    )
    builder.add_edge("human_review", "link_or_create")
    builder.add_edge("link_or_create", "record")
    builder.add_edge("record", END)

    return builder.compile(checkpointer=checkpointer)


class _RefusingGazetteer:
    """Stands in when core-api is unreachable.

    Refuses rather than returning nothing. A gazetteer that answered "no match" for every
    landmark would send every report to division-level or unplaced, which looks like a
    country where nobody can describe where they are.
    """

    async def lookup(self, name: str, *, near_division: str | None = None) -> Any:
        raise RuntimeError(
            "The intake agent has no gazetteer configured, so it cannot place a landmark. "
            "Every report would be unplaced, which is indistinguishable from a country "
            "where nobody says where they are."
        )

    async def division_for(self, lon: float, lat: float) -> Any:
        raise RuntimeError(
            "The intake agent cannot reach core-api to resolve a coordinate to a division."
        )


class _RefusingStore:
    """Stands in when there is nowhere to write. Refuses loudly."""

    async def save_transcript(self, report_id: str, transcript: Transcript) -> None:
        raise RuntimeError("The intake agent has no store configured; nothing was written.")

    async def save_embedding(self, report_id: str, embedding: list[float], model: str) -> None:
        raise RuntimeError("The intake agent has no store configured; nothing was written.")

    async def link_or_create(self, report_id: str, **kwargs: Any) -> Any:
        raise RuntimeError(
            "The intake agent has no store configured, so this report produced no incident. "
            "A run that processes a citizen's report and records nothing is worse than one "
            "that refuses."
        )


class _EmptyIndex:
    """No duplicate search.

    Returns nothing rather than refusing, and that is the one stand-in here that is allowed
    to be quiet: with no index the agent creates a separate incident, which is the safe
    direction. Nothing is merged that should not have been; at worst a dispatcher sees two
    entries and merges them by hand.
    """

    async def neighbours(self, embedding: list[float], **kwargs: Any) -> list[Any]:
        return []


def _eval_build(checkpointer: Any) -> Any:
    """Imported lazily so the production graph does not depend on the eval one."""
    from agent_svc.agents.intake.evaluation import build as build_eval

    return build_eval(checkpointer)


SPEC: Final = AgentSpec(
    name=AGENT,
    subject_type=SUBJECT_TYPE,
    build=build,
    description=(
        "Turns raw citizen reports - trilingual SMS, voice notes, LoRa batches - into "
        "structured, geolocated, non-duplicate incidents, routing anything it cannot do "
        "confidently to a person."
    ),
    degraded_note=(
        "Language detection is a Unicode script test and never needed a model. Extraction "
        "falls back to keyword matching over the trilingual hazard lexicon, at a confidence "
        "below the review threshold, so every report is confirmed by a person. Duplicate "
        "detection falls back to vector similarity alone and flags the ambiguous band "
        "rather than merging it. With no ASR a voice note queues as "
        "audio_pending_transcription, playable by a reviewer and still dispatchable on its "
        "GPS. Slower, fully functional, and labelled DETERMINISTIC throughout."
    ),
    gated=True,
    eval_build=_eval_build,
)
