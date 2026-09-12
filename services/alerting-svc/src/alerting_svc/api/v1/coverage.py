"""Modelled reachability per division.

Answers "if we sent a warning to this division right now, who would we expect to reach?"
before an event rather than after one — which is what lets a DMC officer position a
loudhailer vehicle in advance instead of discovering the gap from a delivery report.

**Every number here is modelled, not measured**, and every response says so. Confusing a
model with a measurement is the specific way this endpoint could do harm: an operator who
believes 94% coverage was observed will not send the vehicle.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope

router = APIRouter(tags=["coverage"])

ReadPrincipal = Depends(require(Scope.ALERT_READ))


class ChannelCoverage(BaseModel):
    """What one channel is modelled to reach in one division."""

    model_config = ConfigDict(frozen=True)

    channel: str
    reachable_fraction: float = Field(ge=0.0, le=1.0)
    simulated: bool = Field(
        description="True when the transport does not exist and the number is a model."
    )
    basis: str = Field(description="Where the figure comes from, in words.")


class CoverageResponse(BaseModel):
    """The reachability picture for one division."""

    model_config = ConfigDict(frozen=True)

    gn_division_code: str
    channels: list[ChannelCoverage]
    best_channel: str | None
    best_fraction: float
    caveat: str = Field(
        description="Shown verbatim. These are modelled figures, never observed delivery."
    )


CAVEAT = (
    "Modelled reachability, not observed delivery. Use /alerts/{id}/delivery/gaps after a "
    "dispatch for what actually happened."
)

# Modelled reach per channel, before any division-specific adjustment.
#
# These are deliberately conservative. A coverage model that flatters itself produces an
# operator who does not send the vehicle, which is the failure that costs someone.
BASELINE: dict[str, tuple[float, str]] = {
    "SMS": (0.82, "handsets with a registered number and cell coverage"),
    "USSD": (0.61, "handsets reachable by a push session while idle"),
    "PUSH": (0.34, "households with the app installed and notifications allowed"),
    "APP": (0.34, "households with the app installed"),
    "RADIO": (0.55, "estimated listenership during a declared emergency"),
    "PAPER_QR": (0.20, "what one officer can cover door to door in a shift"),
}


@router.get("/coverage", response_model=CoverageResponse)
async def division_coverage(
    request: Request,
    principal: Principal = ReadPrincipal,
    gn_division_code: str = Query(max_length=16),
) -> Any:
    """Modelled reachability for one division, per channel.

    The mesh figure is computed from the simulated topology - hop count and battery state
    for that division's node - rather than a constant, because the mesh is the channel
    whose coverage varies most and matters most where the others have failed.
    """
    channels: list[dict[str, Any]] = []

    for channel in request.app.state.channels:
        if channel.name == "LORA":
            fraction = channel.coverage(gn_division_code)
            basis = "simulated mesh: hop count and node battery for this division"
        else:
            fraction, basis = BASELINE.get(channel.name, (0.0, "no model for this channel"))

        channels.append(
            {
                "channel": channel.name,
                "reachable_fraction": round(fraction, 4),
                "simulated": bool(getattr(channel, "simulated", False)),
                "basis": basis,
            }
        )

    channels.sort(key=lambda entry: -entry["reachable_fraction"])
    best = channels[0] if channels else None

    return {
        "gn_division_code": gn_division_code,
        "channels": channels,
        "best_channel": best["channel"] if best else None,
        "best_fraction": best["reachable_fraction"] if best else 0.0,
        "caveat": CAVEAT,
    }
