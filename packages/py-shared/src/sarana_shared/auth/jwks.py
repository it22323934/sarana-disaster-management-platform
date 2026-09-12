"""JWKS publication and the caching client every other service verifies against.

core-api publishes its public key at `/.well-known/jwks.json`. Every other service fetches
it, caches it for ten minutes, and refreshes in the background. They never call core-api
to validate a request: putting a synchronous dependency on one service in the path of
every authorised call would create a single point of failure during exactly the event this
platform exists for.

A stale-but-usable cache is preferred to a hard failure. If the refresh cannot reach
core-api, verification keeps working against the last known key set - a key rotation that
has not propagated is a much smaller problem than a district losing the ability to
authorise anything.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from typing import Any, Final

import httpx
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

JWKS_PATH: Final = "/.well-known/jwks.json"

CACHE_TTL_SECONDS: Final = 600


def _b64url_uint(value: int) -> str:
    """Encode an RSA parameter the way RFC 7518 requires: big-endian, unpadded base64url."""
    length = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()


def key_id(public_key: RSAPublicKey) -> str:
    """A stable identifier derived from the key itself.

    Deriving the id from the key rather than assigning one means a rotated key gets a new
    id automatically, and two deployments holding the same key agree on its name.
    """
    import hashlib

    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()[:16]


def build_jwks(public_key_pem: str) -> dict[str, Any]:
    """Render a public key as a JWKS document.

    Only the public half is ever serialised here. The private key stays in KMS on AWS and
    in a file mounted read-only in local development.
    """
    loaded = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    if not isinstance(loaded, RSAPublicKey):
        raise TypeError(f"expected an RSA public key, got {type(loaded).__name__}")

    numbers = loaded.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": key_id(loaded),
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }


def public_key_from_private(private_key_pem: str) -> str:
    """Derive the public PEM from a private key, so only one file needs configuring."""
    loaded = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    if not isinstance(loaded, RSAPrivateKey):
        raise TypeError(f"expected an RSA private key, got {type(loaded).__name__}")
    return (
        loaded.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


@dataclass
class JWKSCache:
    """Fetches and caches core-api's public keys for local token verification.

    The cache is served past its TTL when a refresh fails. A key rotation that has not
    propagated yet is a far smaller problem than a whole district losing the ability to
    authorise anything because one service was briefly unreachable.
    """

    base_url: str
    ttl_seconds: int = CACHE_TTL_SECONDS
    client: httpx.AsyncClient | None = None

    _keys: dict[str, str] = field(default_factory=dict, repr=False)
    _fetched_at: float = field(default=0.0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def url(self) -> str:
        """Where the key set is published."""
        return f"{self.base_url.rstrip('/')}{JWKS_PATH}"

    @property
    def is_fresh(self) -> bool:
        """Whether the cached key set is inside its TTL."""
        return bool(self._keys) and (utc_now().timestamp() - self._fetched_at) < self.ttl_seconds

    async def public_key_pem(self, kid: str | None = None) -> str:
        """Return a PEM public key, fetching the set if it is missing or stale.

        Raises:
            LookupError: if no key set could be obtained at all. A service that has never
                reached core-api cannot verify anything and must say so.
        """
        if not self.is_fresh:
            await self.refresh()

        if kid is not None and kid in self._keys:
            return self._keys[kid]
        if self._keys:
            # Single-key deployments are the norm; during a rotation the kid selects.
            return next(iter(self._keys.values()))

        raise LookupError(
            f"no signing keys available from {self.url}; token verification is impossible "
            "until core-api has been reachable at least once"
        )

    async def refresh(self) -> None:
        """Fetch the key set. A failure leaves any existing cache in place."""
        async with self._lock:
            owns_client = self.client is None
            client = self.client or httpx.AsyncClient(timeout=5.0)
            try:
                response = await client.get(self.url)
                response.raise_for_status()
                document = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                if self._keys:
                    _log.warning("jwks_refresh_failed_serving_stale", url=self.url, error=str(exc))
                    return
                _log.error("jwks_refresh_failed_no_cache", url=self.url, error=str(exc))
                return
            finally:
                if owns_client:
                    await client.aclose()

            self._keys = {entry["kid"]: _jwk_to_pem(entry) for entry in document.get("keys", [])}
            self._fetched_at = utc_now().timestamp()
            _log.info("jwks_refreshed", url=self.url, key_count=len(self._keys))

    async def run_background_refresh(self) -> None:
        """Refresh on a loop, so a rotation propagates without a request paying for it."""
        while True:
            await asyncio.sleep(self.ttl_seconds / 2)
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the refresher must outlive one bad fetch
                _log.exception("jwks_background_refresh_failed", url=self.url)

    def start(self) -> None:
        """Launch the background refresher."""
        if self._task is not None:
            raise RuntimeError("the JWKS refresher is already running")
        self._task = asyncio.create_task(self.run_background_refresh(), name="sarana-jwks")

    async def stop(self) -> None:
        """Cancel the refresher and wait for it to finish."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None


def _jwk_to_pem(entry: dict[str, Any]) -> str:
    """Rebuild a PEM public key from a JWK entry."""
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    def decode(value: str) -> int:
        padding = "=" * (-len(value) % 4)
        return int.from_bytes(base64.urlsafe_b64decode(value + padding), "big")

    numbers = RSAPublicNumbers(e=decode(entry["e"]), n=decode(entry["n"]))
    return (
        numbers.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
