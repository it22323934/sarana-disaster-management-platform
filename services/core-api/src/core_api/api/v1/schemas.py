"""Request and response bodies for the core-api v1 surface.

Kept separate from the routers so the wire contract is readable in one place - which is
what the generated TypeScript client and any government integrator will actually read.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.domain.localised import Locale


class LoginRequest(BaseModel):
    """Email, password and TOTP. Officers and operators only; citizens use OTP."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=512)
    # Required at login for every officer account. The step-up check later in the session
    # is a second, separate verification.
    totp_code: str | None = Field(default=None, max_length=8)
    device_id: str | None = Field(default=None, max_length=64)
    device_platform: str = Field(default="web", max_length=20)


class ServiceTokenRequest(BaseModel):
    """A service asking for an access token with its own credential.

    Deliberately shaped like OAuth 2.0's client-credentials grant. Not because the
    standard is required here, but because every operator and every library already knows
    what these three fields mean, and a bespoke shape would be one more thing to explain
    in a security review.
    """

    model_config = ConfigDict(extra="forbid")

    grant_type: str = Field(
        default="client_credentials",
        description="Only client_credentials. Present so the request is recognisable.",
    )
    client_id: str = Field(min_length=1, max_length=64)
    client_secret: str = Field(min_length=1, max_length=256)
    scope: str | None = Field(
        default=None,
        max_length=1024,
        description="Space-separated scopes to narrow the token to. Omit for everything "
        "the credential holds. Asking for more than it holds is not an error - the token "
        "carries the intersection - so a service that adds a scope before its credential "
        "is updated degrades rather than failing closed mid-event.",
    )


class ServiceTokenResponse(BaseModel):
    """A granted machine token. No refresh token: a service re-authenticates."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: str = "Bearer"  # noqa: S105 - the OAuth scheme name, not a credential
    expires_in: int = Field(description="Access token lifetime in seconds")
    scope: str = Field(
        description="Space-separated scopes actually granted. Read it: it may be narrower "
        "than what was asked for, and silently acting as though it were not is how a "
        "service discovers a missing permission during an incident."
    )


class TokenResponse(BaseModel):
    """What a successful authentication returns."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # noqa: S105 - the OAuth scheme name, not a credential
    expires_in: int = Field(description="Access token lifetime in seconds")
    # Present when the account has no confirmed second factor yet. The client must send
    # the user through enrolment before anything gated will work.
    mfa_enrolment_required: bool = False


class RefreshRequest(BaseModel):
    """Exchange a refresh token for a new pair. Single use, rotating."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    """End one session, or every session on the device."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=512)
    all_devices: bool = False


class OTPRequest(BaseModel):
    """Ask for a verification code. Citizens have no password."""

    model_config = ConfigDict(extra="forbid")

    msisdn: str = Field(min_length=9, max_length=20, description="Sri Lanka mobile number")
    # Falls back to the household's stored preference, then to Sinhala. A Tamil-speaking
    # family receiving a Sinhala-only code is the Ditwah failure in miniature.
    locale: Locale | None = None


class OTPRequestResponse(BaseModel):
    """Deliberately says nothing about whether the number is known.

    Confirming that a number is registered would turn this endpoint into a way of
    checking who is on the platform, which during a disaster is information about who has
    reported damage.
    """

    model_config = ConfigDict(frozen=True)

    sent: bool = True
    expires_in: int = Field(description="Code lifetime in seconds")
    attempts_allowed: int


class OTPVerifyRequest(BaseModel):
    """Prove possession of the number."""

    model_config = ConfigDict(extra="forbid")

    msisdn: str = Field(min_length=9, max_length=20)
    code: str = Field(min_length=4, max_length=8)
    device_id: str | None = Field(default=None, max_length=64)
    device_platform: str = Field(default="android", max_length=20)


class TOTPEnrolResponse(BaseModel):
    """A new second factor, not yet active.

    Inactive until confirmed, so a mistyped QR scan cannot lock someone out of their own
    account. The recovery codes are shown exactly once.
    """

    model_config = ConfigDict(frozen=True)

    provisioning_uri: str
    recovery_codes: list[str]


class TOTPConfirmRequest(BaseModel):
    """Activate an enrolment by producing a code from it."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=8)


class StepUpRequest(BaseModel):
    """Re-prove the second factor before a human-gated action."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=8)


class StepUpResponse(BaseModel):
    """A short-lived access token carrying a fresh step-up stamp."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    expires_in: int
    step_up_expires_in: int = Field(
        description="Seconds for which this token authorises a human-gated action"
    )


class CapabilityTokenRequest(BaseModel):
    """Ask for an offline capability token before going into the field."""

    model_config = ConfigDict(extra="forbid")

    gn_division_code: str = Field(pattern=r"^LK-\d{2}-\d{2}-\d{3}$")
    device_id: str = Field(min_length=1, max_length=64)


class CapabilityTokenResponse(BaseModel):
    """The offline credential, and a plain statement of what it can do."""

    model_config = ConfigDict(frozen=True)

    capability_token: str
    expires_in: int
    gn_division_code: str
    permits: list[str] = Field(
        description="Every action this token authorises. Deliberately a short list."
    )
