"""Domain rules for incident-svc.

Deliberately free of FastAPI and SQLAlchemy. The state machine, the triage formula, the
dedup rule and the dispatch gate are the things a reviewer needs to be able to read and
argue with, and none of them should require knowing how a request reaches them.
"""

from __future__ import annotations

from incident_svc.domain.dedup import (
    PROXIMITY_METRES,
    WINDOW_MINUTES,
    Candidate,
    DuplicateCandidate,
    find_candidates,
    is_candidate,
)
from incident_svc.domain.dispatch_gate import (
    AlreadyDecided,
    GateDecision,
    GateRefused,
    GraphResumeFailed,
    NullResumer,
    RejectionReason,
    StepUpFailed,
    ThreadResumer,
    approve,
    reject,
)
from incident_svc.domain.media import (
    MAX_PHOTO_BYTES,
    MAX_PHOTOS_PER_REPORT,
    MediaRefused,
    UploadGrant,
    UploadRequest,
    grant_for_audio,
    grant_for_photo,
    object_key,
)
from incident_svc.domain.state_machine import (
    INCIDENT_TRANSITIONS,
    REPORT_TRANSITIONS,
    IllegalTransition,
    assert_transition,
    can_transition,
    legal_next,
)
from incident_svc.domain.triage import TriageInput, TriageResult, score, score_row

__all__ = [
    "INCIDENT_TRANSITIONS",
    "MAX_PHOTOS_PER_REPORT",
    "MAX_PHOTO_BYTES",
    "PROXIMITY_METRES",
    "REPORT_TRANSITIONS",
    "WINDOW_MINUTES",
    "AlreadyDecided",
    "Candidate",
    "DuplicateCandidate",
    "GateDecision",
    "GateRefused",
    "GraphResumeFailed",
    "IllegalTransition",
    "MediaRefused",
    "NullResumer",
    "RejectionReason",
    "StepUpFailed",
    "ThreadResumer",
    "TriageInput",
    "TriageResult",
    "UploadGrant",
    "UploadRequest",
    "approve",
    "assert_transition",
    "can_transition",
    "find_candidates",
    "grant_for_audio",
    "grant_for_photo",
    "is_candidate",
    "legal_next",
    "object_key",
    "reject",
    "score",
    "score_row",
]
