"""One adapter per delivery channel, all satisfying the same contract."""

from __future__ import annotations

from alerting_svc.adapters.channels.base import (
    Channel,
    ChannelResult,
    DeliveryStatus,
    Message,
    Receipt,
    Target,
    languages_for,
)

__all__ = [
    "Channel",
    "ChannelResult",
    "DeliveryStatus",
    "Message",
    "Receipt",
    "Target",
    "languages_for",
]
