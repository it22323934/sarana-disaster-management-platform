"""The guard that keeps an offline capability token to its one job.

The capability token is the credential most likely to be physically lost - it lives on a
handset carried through a disaster zone. Its defence is not secrecy, it is that it can
almost nothing. This module is where "almost nothing" is enforced, on every endpoint,
rather than each handler being trusted to notice.
"""

from __future__ import annotations

from typing import Final

from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.errors import Forbidden

# The single permission an offline token carries. Kept here rather than imported from
# core-api so that every service enforces the same list without depending on core-api.
CAPABILITY_SCOPES: Final[frozenset[Scope]] = frozenset({Scope.ASSESSMENT_WRITE})


def assert_capability_permits(principal: Principal, scope: Scope) -> None:
    """Refuse an offline token on anything but drafting an assessment.

    Raises:
        Forbidden: naming the token kind, so the field app can tell the officer they need
            to reconnect rather than showing them a generic permission error they cannot
            act on.
    """
    if not principal.is_offline_capability:
        return
    if scope in CAPABILITY_SCOPES:
        return

    raise Forbidden(
        "You are working offline. This action needs a connection - reconnect and it will "
        "be available again.",
        context={
            "subject_id": principal.subject_id,
            "required_scope": scope.value,
            "token_kind": "capability",
            "device_id": principal.device_id,
        },
    )
