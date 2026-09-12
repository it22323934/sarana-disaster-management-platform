"""A small in-process TTL cache.

Deliberately in-process rather than Redis. The things cached here - the administrative
hierarchy and the coordinate-to-division answer - change roughly never and are identical
for every replica, so a network hop to share them would cost more than recomputing them.
Redis is reserved for state that must actually be shared.

Entries carry their own expiry and the cache keeps a hard size cap, because an unbounded
cache on a service that must not fall over is a memory leak waiting for a busy day.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

from sarana_shared.domain.time import utc_now


@dataclass(frozen=True, slots=True)
class Cached[V]:
    """A value and the moment it stops being fresh."""

    value: V
    expires_at: float
    stored_at: float

    def is_fresh(self, now: float) -> bool:
        return now < self.expires_at


class TTLCache[V]:
    """Bounded, thread-safe, least-recently-used with a per-entry TTL.

    `get` returns fresh entries only. `get_stale` also returns expired ones, which is how
    a read endpoint degrades instead of failing when its database is unreachable: a
    division boundary from ten minutes ago is still the right answer, and a blank screen
    during a cyclone is worse than a stale one.
    """

    def __init__(self, *, max_entries: int = 4096, ttl_seconds: float = 3600.0) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._entries: OrderedDict[str, Cached[V]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.stale_serves = 0

    @staticmethod
    def _now() -> float:
        return utc_now().timestamp()

    def get(self, key: str) -> V | None:
        """A fresh value, or None."""
        now = self._now()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            if not entry.is_fresh(now):
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return entry.value

    def get_stale(self, key: str) -> tuple[V, bool] | None:
        """A value and whether it is stale, or None if never cached.

        The caller decides what to do with a stale hit; it must set `X-Sarana-Stale: true`
        on any response it serves from one, so a client can tell the difference.
        """
        now = self._now()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            fresh = entry.is_fresh(now)
            if not fresh:
                self.stale_serves += 1
            self._entries.move_to_end(key)
            return entry.value, not fresh

    def put(self, key: str, value: V, *, ttl_seconds: float | None = None) -> None:
        now = self._now()
        ttl = self._ttl if ttl_seconds is None else ttl_seconds
        with self._lock:
            self._entries[key] = Cached(value=value, expires_at=now + ttl, stored_at=now)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
