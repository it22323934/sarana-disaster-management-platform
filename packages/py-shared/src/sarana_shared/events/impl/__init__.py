"""EventBus implementations, selected by `SARANA_EVENT_BUS`.

  redis        Redis Streams. Local development and CI.
  eventbridge  EventBridge + SQS + Archive. AWS.
  memory       In-process. Unit tests.

A fourth, MSK, is the documented Phase 2 seam (ADR-003). The port in `bus.py` is written
so it can be added without touching a caller.
"""

from sarana_shared.events.impl.eventbridge import EventBridgeEventBus
from sarana_shared.events.impl.in_memory import InMemoryEventBus
from sarana_shared.events.impl.redis_streams import RedisStreamsEventBus

__all__ = ["EventBridgeEventBus", "InMemoryEventBus", "RedisStreamsEventBus"]
