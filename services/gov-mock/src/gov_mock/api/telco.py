"""Telco gateway routes: SMS, USSD, message status, coverage.

Three operators with genuinely different behaviour — see `gov_mock.data.telco` for why each
difference exists. The one worth restating here: **HUTCH never sends a receipt for about 2%
of messages**. Those come back `UNKNOWN`, not `FAILED`, and a caller must carry that state
rather than resolve it. A delivery map that folded `UNKNOWN` into delivered would claim a
village was warned when nobody knows.

Submission is subject to a per-operator throughput cap, so a national fan-out is partially
accepted and the rest has to be resent. Partial acceptance is not an error. A caller that
treats it as one and resends the whole batch doubles everybody's messages during the exact
hour the gateway is already congested.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from gov_mock.api.deps import (
    SimulatedHoursDep,
    SimulatedNowDep,
    StateDep,
    mock_json,
)
from gov_mock.data import telco as telco_data
from gov_mock.data.districts import district_for
from gov_mock.state import Message

router = APIRouter(prefix="/telco/v1", tags=["telco"])

# The longest a single SMS body may be before it becomes multiple segments. A trilingual
# warning does not fit in one; the platform sends one language per SMS for that reason.
MAX_SMS_LENGTH: Final = 918

# Most messages a single submission may carry. Real gateways cap batch size well below
# what a national fan-out needs, which is why the caller has to chunk.
MAX_BATCH: Final = 500


class SmsIn(BaseModel):
    """One outbound message."""

    model_config = ConfigDict(extra="forbid")

    recipient_ref_hash: str = Field(min_length=1, max_length=128)
    body: str = Field(min_length=1, max_length=MAX_SMS_LENGTH)
    language: str = Field(min_length=2, max_length=8)
    priority: bool = False


class SmsBatchIn(BaseModel):
    """A submission of one or more messages."""

    model_config = ConfigDict(extra="forbid")

    messages: list[SmsIn] = Field(min_length=1, max_length=MAX_BATCH)


class UssdIn(BaseModel):
    """A USSD session push."""

    model_config = ConfigDict(extra="forbid")

    recipient_ref_hash: str = Field(min_length=1, max_length=128)
    menu_id: str = Field(min_length=1, max_length=64)


@router.post("/sms/send", summary="Submit one or more SMS")
def send_sms(payload: SmsBatchIn, state: StateDep, now: SimulatedNowDep) -> Any:
    """Submit messages, subject to the per-operator throughput cap.

    Priority messages jump the queue and are accepted first. A life-safety warning sharing
    a queue with anything else is a design that kills people slowly, so the ordering is
    applied here rather than left to whatever order the caller happened to build the batch
    in.
    """
    ordered = sorted(payload.messages, key=lambda message: not message.priority)

    accepted: list[dict[str, Any]] = []
    rejected: list[str] = []
    per_operator: dict[telco_data.Operator, int] = {}
    lowest_cap = min(profile.throughput_per_second for profile in telco_data.PROFILES.values())

    for message in ordered:
        operator = telco_data.operator_for(message.recipient_ref_hash, seed=state.seed)
        profile = telco_data.PROFILES[operator]
        taken = per_operator.get(operator, 0)

        if taken >= profile.throughput_per_second:
            rejected.append(message.recipient_ref_hash)
            continue
        per_operator[operator] = taken + 1

        sequence = state.next_sequence()
        message_id = f"MOCK-SMS-{sequence:09d}"
        state.messages[message_id] = Message(
            message_id=message_id,
            recipient_ref_hash=message.recipient_ref_hash,
            body=message.body,
            language=message.language,
            accepted_at=now,
        )
        accepted.append(
            {
                "message_id": message_id,
                "recipient_ref_hash": message.recipient_ref_hash,
                "operator": operator.value,
                "state": "QUEUED",
                "accepted_at": now.isoformat(),
                # False for the operator that sends no receipts for this message. Present
                # so a caller can tell "no DLR yet" from "no DLR ever" — different waits,
                # and only one of them is worth continuing to poll.
                "dlr_expected": not telco_data.outcome_for(
                    message_id, message.recipient_ref_hash, seed=state.seed
                ).silent,
            }
        )

    return mock_json(
        {
            "accepted": accepted,
            "rejected": rejected,
            "throughput_limit_per_second": lowest_cap,
        }
    )


@router.post("/ussd/push", summary="Push a USSD session", status_code=201)
def push_ussd(payload: UssdIn, state: StateDep, now: SimulatedNowDep) -> Any:
    """Push a USSD session to a handset."""
    operator = telco_data.operator_for(payload.recipient_ref_hash, seed=state.seed)
    sequence = state.next_sequence()
    return mock_json(
        {
            "push": {
                "session_id": f"MOCK-USSD-{sequence:08d}",
                "recipient_ref_hash": payload.recipient_ref_hash,
                "operator": operator.value,
                "accepted_at": now.isoformat(),
            }
        },
        status_code=201,
    )


@router.get("/sms/{message_id}", summary="Message status")
def message(message_id: str, state: StateDep, now: SimulatedNowDep) -> Any:
    """The gateway's current view of one message.

    A message stays `SENT` until its operator's receipt latency has elapsed in simulated
    time, then resolves to `DELIVERED`, `FAILED` or — for the operator that sends no
    receipts — stays `UNKNOWN` forever. Advancing the clock is what moves it.
    """
    found = state.messages.get(message_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such message")

    outcome = telco_data.outcome_for(message_id, found.recipient_ref_hash, seed=state.seed)
    profile = telco_data.PROFILES[outcome.operator]
    elapsed = (now - found.accepted_at).total_seconds()

    if elapsed < profile.dlr_latency_seconds:
        state_name = "SENT"
        reason = None
    else:
        state_name = outcome.state
        reason = outcome.failure_reason

    return mock_json(
        {
            "message": {
                "message_id": message_id,
                "operator": outcome.operator.value,
                "state": state_name,
                "updated_at": now.isoformat(),
                "failure_reason": reason,
            }
        }
    )


@router.get("/coverage", summary="Modelled coverage for a GN division")
def coverage(
    state: StateDep,
    now: SimulatedNowDep,
    hours: SimulatedHoursDep,
    gn_division_id: str = Query(description="GN division code"),
) -> Any:
    """Modelled mobile coverage for one division, after power loss and battery drain."""
    if district_for(gn_division_id) is None:
        raise HTTPException(status_code=404, detail="No such GN division")

    try:
        modelled = telco_data.coverage_for(
            gn_division_id, hours_since_landfall=hours, seed=state.seed
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return mock_json(
        {
            "coverage": {
                "gn_division_code": modelled.gn_division_code,
                "percent": modelled.percent,
                "operators": [operator.value for operator in modelled.operators],
                "sites_on_battery": modelled.sites_on_battery,
                "sites_down": modelled.sites_down,
                "measured_at": now.isoformat(),
            }
        }
    )
