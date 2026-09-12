"""`/.well-known/jwks.json` - the public half of the signing key.

core-api is the only issuer. Every other service fetches this document, caches it for ten
minutes and verifies tokens locally. None of them call core-api to check a request: a
synchronous dependency on one service in the path of every authorised call would be a
single point of failure sitting directly in the path of the event this platform exists
for.

Served anonymously and cacheable. There is nothing secret in it - that is the whole
property of asymmetric signing, and publishing it is what lets verification be local.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from core_api.config import Settings
from sarana_shared.auth.jwks import build_jwks, public_key_from_private


def build_jwks_router(settings: Settings) -> APIRouter:
    """Build the router, reading the key once at startup rather than per request."""
    document = _load_document(settings)

    jwks_router = APIRouter(tags=["operations"], include_in_schema=False)

    @jwks_router.get("/.well-known/jwks.json")
    async def jwks(response: Response) -> dict[str, Any]:
        # Half the cache TTL clients use, so a rotation propagates before their copy is
        # even stale. A key rotation nobody notices is the point.
        response.headers["Cache-Control"] = "public, max-age=300"
        return document

    return jwks_router


def _load_document(settings: Settings) -> dict[str, Any]:
    """Read the public key and render it as a JWKS document.

    Derived from the private key when core-api holds one, so a deployment cannot end up
    publishing a public key that does not match what it is signing with - a failure that
    would look like every token being forged.
    """
    if settings.jwt_private_key_path is not None:
        private_pem = settings.jwt_private_key_path.read_text(encoding="utf-8")
        return build_jwks(public_key_from_private(private_pem))
    return build_jwks(settings.jwt_public_key_path.read_text(encoding="utf-8"))
