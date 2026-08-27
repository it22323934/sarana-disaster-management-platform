"""Per-principal rate limiting.

The limits differ by who is calling, not by which endpoint is called. A citizen reporting
a flood and an operator running a console are doing different jobs at different rates, and
one shared limit would either throttle the operator or leave the public endpoints open to
a scraper.

Anonymous callers are limited per IP. That is imperfect behind a shared NAT, which is why
the anonymous limit is the only one generous enough to absorb a village behind one
address doing the obvious thing at once.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Final

from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Role
from sarana_shared.domain.time import utc_now

WINDOW_SECONDS: Final = 60.0

# Requests per minute, from the build brief.
CITIZEN_LIMIT: Final = 60
OFFICER_LIMIT: Final = 300
OPERATOR_LIMIT: Final = 600
ANONYMOUS_LIMIT: Final = 30

# Roles that count as "operator" for rate limiting: the console-driving roles that poll.
_OPERATOR_ROLES: Final = frozenset(
    {Role.DMC_OPERATOR, Role.DISPATCHER, Role.ADMIN, Role.AGENT, Role.SERVICE}
)
_OFFICER_ROLES: Final = frozenset(
    {Role.GN_OFFICER, Role.DS_APPROVER, Role.DISTRICT_APPROVER, Role.AUDITOR}
)


def limit_for(principal: Principal | None) -> int:
    """The per-minute allowance for a caller.

    The most generous applicable role wins. Someone who is both an officer and an
    operator is doing the operator's job when they hit the operator's endpoints.
    """
    if principal is None:
        return ANONYMOUS_LIMIT
    roles = set(principal.roles)
    if roles & _OPERATOR_ROLES:
        return OPERATOR_LIMIT
    if roles & _OFFICER_ROLES:
        return OFFICER_LIMIT
    return CITIZEN_LIMIT


def bucket_key(principal: Principal | None, client_ip: str | None) -> str:
    """What the limit is counted against.

    A principal is counted by subject, so moving between devices or networks does not
    reset the allowance. Anonymous traffic falls back to the IP.
    """
    if principal is not None:
        return f"sub:{principal.subject_id}"
    return f"ip:{client_ip or 'unknown'}"


@dataclass(slots=True)
class _Window:
    started_at: float
    count: int


@dataclass(frozen=True, slots=True)
class Decision:
    """Whether a request may proceed, and what to tell the caller if not."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RateLimiter:
    """Fixed-window counters, bounded in size.

    A fixed window can admit up to twice the limit across a boundary. That is accepted
    deliberately: the alternative costs more state per caller, and the limit here exists
    to stop runaway clients rather than to meter a paid API.
    """

    def __init__(
        self, *, max_buckets: int = 100_000, window_seconds: float = WINDOW_SECONDS
    ) -> None:
        self._windows: OrderedDict[str, _Window] = OrderedDict()
        self._lock = threading.Lock()
        self._max_buckets = max_buckets
        self._window_seconds = window_seconds

    @staticmethod
    def _now() -> float:
        return utc_now().timestamp()

    def check(self, key: str, limit: int) -> Decision:
        """Count one request against a bucket and decide."""
        now = self._now()
        with self._lock:
            window = self._windows.get(key)

            if window is None or now - window.started_at >= self._window_seconds:
                window = _Window(started_at=now, count=0)
                self._windows[key] = window

            self._windows.move_to_end(key)
            window.count += 1

            while len(self._windows) > self._max_buckets:
                self._windows.popitem(last=False)

            elapsed = now - window.started_at
            retry_after = max(1, int(self._window_seconds - elapsed) + 1)
            remaining = max(0, limit - window.count)

            return Decision(
                allowed=window.count <= limit,
                limit=limit,
                remaining=remaining,
                retry_after=retry_after,
            )

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()
