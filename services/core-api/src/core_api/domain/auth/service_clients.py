"""The client-credentials grant: what a machine may ask for, and what it may never have.

This is the mechanism that replaces `SARANA_INCIDENT_SERVICE_TOKEN` — a never-expiring
token minted by a script and pasted into an environment file, which could not be rotated
without a redeploy, could not be revoked at all, and granted every scope the SERVICE role
had whether the caller needed them or not.

Everything here is a refusal by default, and the order the checks run in is deliberate.

**The ceiling is the SERVICE role, not the request.** A client asks for scopes and gets the
intersection of what it asked for, what it was configured with, and what SERVICE grants.
Three narrowings, and the widest of them is fixed in code. A row in the database cannot
widen a credential beyond the role, so compromising the table does not compromise the
platform.

**The human gates are unreachable.** `sarana_shared.auth` refuses `disbursement:release`
and `dispatch:commit` to every machine principal, so they are already impossible — and they
are refused *again* here, at configuration time, so a credential that would need them
cannot even be created. Defence in depth on the one boundary where being wrong means money
moving without a person deciding.

**A failed grant says nothing useful to the caller.** Wrong client id, wrong secret,
revoked client and unknown client all return the same refusal. Distinguishing them tells an
attacker which half they got right.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sarana_shared.auth.grants import ScopeGrant, ScopeType
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, ROLE_SCOPES, Role, Scope

# The widest a machine credential can ever be. Fixed in code rather than in the database,
# so a compromised `admin.service_client` row cannot widen one.
SERVICE_CEILING: Final[frozenset[Scope]] = ROLE_SCOPES[Role.SERVICE]

# How long a granted token lives. Deliberately the same as a human's: the whole reason this
# exists is that the credential it replaces never expired, and a "machines are different"
# exemption is how that comes back.
#
# Short enough that revoking a client takes effect within a quarter of an hour, long enough
# that a service is not spending its time re-authenticating during a national fan-out.
TOKEN_TTL_SECONDS: Final = 900

# Minimum secret length. These are machine-generated and never typed, so there is no
# usability argument for anything shorter.
MIN_SECRET_LENGTH: Final = 32


class ClientRefused(ValueError):
    """The credential cannot be granted, or cannot be configured as asked."""


@dataclass(frozen=True, slots=True)
class ServiceClientConfig:
    """A machine credential as it is stored.

    Validated on construction, so a row that cannot be turned into a legal grant is
    rejected where somebody is watching rather than at the moment a service needs it.
    """

    client_id: str
    allowed_scopes: frozenset[Scope]
    scope_type: ScopeType
    scope_code: str
    active: bool = True

    def __post_init__(self) -> None:
        if not self.allowed_scopes:
            raise ClientRefused(
                f"{self.client_id}: a credential granting no scopes can do nothing and "
                "looks like it works. Give it the scopes it needs or do not create it."
            )

        # Checked before the ceiling, even though the ceiling would currently catch it
        # too. Two reasons: this is the more alarming condition and deserves the clearer
        # message, and if a human gate were ever added to the SERVICE role the ceiling
        # check would start passing while this one would not.
        gated = self.allowed_scopes & HUMAN_GATE_SCOPES
        if gated:
            raise ClientRefused(
                f"{self.client_id} asks for {sorted(scope.value for scope in gated)}, "
                "which is a human gate. No machine credential may hold one, and no "
                "configuration makes one possible."
            )

        beyond = self.allowed_scopes - SERVICE_CEILING
        if beyond:
            raise ClientRefused(
                f"{self.client_id} asks for {sorted(scope.value for scope in beyond)}, "
                "which the SERVICE role does not grant. A machine credential cannot be "
                "wider than the role it holds."
            )


def parse_scopes(values: list[str] | tuple[str, ...]) -> frozenset[Scope]:
    """Turn stored scope strings into `Scope` members.

    Raises:
        ClientRefused: for a value that is not a scope. A credential referencing a scope
            that no longer exists is a silent downgrade otherwise - the service keeps
            authenticating and quietly loses the permission it was created for.
    """
    parsed: set[Scope] = set()
    for value in values:
        try:
            parsed.add(Scope(value))
        except ValueError as error:
            raise ClientRefused(
                f"{value!r} is not a scope this platform defines. If it was renamed, the "
                "credential needs updating rather than silently losing the permission."
            ) from error
    return frozenset(parsed)


def granted_scopes(
    config: ServiceClientConfig, requested: frozenset[Scope] | None = None
) -> frozenset[Scope]:
    """What this client actually gets on this request.

    The intersection of three things: what it asked for, what it was configured with, and
    what the SERVICE role allows. A caller asking for more than it holds is not an error -
    it gets what it holds - because a service adding a scope to its request before the
    credential is updated should degrade, not fail closed in the middle of an event.

    A caller asking for *nothing* gets everything it was configured with, which is the
    ordinary case: most services want their whole credential.
    """
    if requested is None:
        return config.allowed_scopes & SERVICE_CEILING
    return requested & config.allowed_scopes & SERVICE_CEILING


def grants_for(config: ServiceClientConfig, scopes: frozenset[Scope]) -> frozenset[ScopeGrant]:
    """Build the area-pinned grants for a token.

    Every scope is pinned to the client's own area, exactly as a human's role assignment
    is. A machine credential is subject to row-level security on the same terms as a
    person, which is what makes "the service can only see its own district" a property of
    the database rather than of the service's own good behaviour.
    """
    return frozenset(
        ScopeGrant(scope=scope, scope_type=config.scope_type, scope_code=config.scope_code)
        for scope in scopes
    )
