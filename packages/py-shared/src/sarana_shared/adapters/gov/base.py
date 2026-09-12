"""The contract between SARANA and every government or telco system it depends on.

Each system in this package is expressed three times, and the split is the whole point:

  **A Protocol** — what SARANA needs from that system, and nothing else. A service depends
  on this, never on a concrete client. It is also the smallest honest statement of what has
  to be asked for in a data-sharing negotiation.

  **A MockClient** — talks HTTP to `gov-mock`. It is not an in-process fake: it crosses a
  socket, parses a real response, and fails the way a network fails. A mock that cannot
  time out proves nothing about the code that has to survive a timeout.

  **A RealClient** — every method raises `NotImplementedError`, and the class docstring
  names the real endpoint, the credential it needs and the agreement that has to exist
  first. These are not placeholders to be tidied away. They are the written record of what
  remains to be negotiated with each agency, and they double as the technical annexe to
  each data-sharing agreement. Keep them accurate.

Swapping a mock for the real thing is then a factory call and a credential, not a rewrite.

Two properties hold across every mock in this package and are asserted here rather than
trusted:

  Every mock response carries `X-Sarana-Mock: true`, and every JSON body carries a
  top-level `"source": "MOCK"`. `MockGovClient` **refuses** a response without them. A
  client pointed by accident at a real agency endpoint fails loudly at the first call
  instead of quietly feeding real warnings into a demo, or a demo's synthetic rainfall
  into something that matters.

  Every failure surfaces as a subclass of `GovUpstreamError`, which is a `SaranaError`
  with status 503. A service that forgets to catch one still returns "upstream
  unavailable" rather than a 500. During a cyclone the difference is whether an operator
  reads "the Met feed is down" or "something went wrong".
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Any, ClassVar, Final, NoReturn, Self
from xml.etree import ElementTree
from xml.etree.ElementTree import Element

import httpx
import structlog

from sarana_shared.domain.ids import get_correlation_id
from sarana_shared.errors import NotFound, UpstreamUnavailable

_log = structlog.get_logger(__name__)

# The two markers. Both are mandatory on every mock response; neither has a config flag
# that turns it off, because the one time it would be turned off is a demo.
MOCK_HEADER: Final = "X-Sarana-Mock"
MOCK_HEADER_VALUE: Final = "true"
MOCK_SOURCE_FIELD: Final = "source"
MOCK_SOURCE_VALUE: Final = "MOCK"

CORRELATION_HEADER: Final = "X-Correlation-Id"

# Government systems are slow. These are deliberately generous compared with an internal
# call, and deliberately finite: an agent waiting forever on a met feed is an agent that
# never produces the forecast somebody is waiting for.
CONNECT_TIMEOUT: Final = 3.0
READ_TIMEOUT: Final = 10.0

# Statuses that mean "the upstream did not answer in time" rather than "the upstream
# refused". Request Timeout and Gateway Timeout are the two a real gateway returns.
TIMEOUT_STATUSES: Final[frozenset[int]] = frozenset({408, 504})


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------


class GovUpstreamError(UpstreamUnavailable):
    """An external system failed. Base of every typed failure in this package.

    Subclasses distinguish *how* it failed, because the right response differs: a timeout
    is worth retrying later, a malformed payload is worth paging someone, and a refusal is
    usually a credential that expired.
    """

    slug = "upstream-unavailable"
    title = "Upstream system unavailable"

    def __init__(self, system: str, detail: str, **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)
        self.system = system
        self.context.setdefault("upstream_system", system)


class GovTimeout(GovUpstreamError):
    """The system did not answer inside its timeout. Nothing is known about the request.

    For a write this is the dangerous one: the call may have been applied. Every write in
    this package is therefore idempotent on a client-supplied reference, so a retry after
    a timeout cannot produce a second payment or a second claim.
    """

    slug = "upstream-timeout"
    title = "Upstream system timed out"


class GovRefused(GovUpstreamError):
    """The system answered with an error status."""

    slug = "upstream-refused"
    title = "Upstream system refused the request"

    def __init__(self, system: str, detail: str, *, status: int, **kwargs: Any) -> None:
        super().__init__(system, detail, **kwargs)
        self.upstream_status = status
        self.context["upstream_status"] = status


class GovMalformedResponse(GovUpstreamError):
    """The system answered with something we cannot parse, or cannot trust.

    Raised for a broken body and, just as importantly, for a response missing its mock
    markers. Real agency APIs return XML where they promised JSON often enough that this
    is a normal operating condition, not an alarm.
    """

    slug = "upstream-malformed"
    title = "Upstream system returned an unusable response"


class GovRecordNotFound(NotFound):
    """The system answered, and the record genuinely does not exist.

    A real answer, not a failure — 404, not 503. Distinct from `GovUpstreamError` because
    a missing record is a fact to record about a household, and an unreachable registry is
    a fact about the platform. Conflating them is how a family ends up excluded from aid
    by an outage.
    """

    slug = "upstream-record-not-found"
    title = "No such record in the upstream system"


# --------------------------------------------------------------------------------------
# The integration register
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Integration:
    """What has to exist before one system's `RealClient` can be written.

    Held as data rather than prose so it can be enumerated: `integration_register()`
    prints the whole outstanding negotiation list, and a test asserts every RealClient
    declares one. A stub that forgets what credential it needs is a stub that gets
    rewritten from scratch by whoever inherits it.
    """

    system: str
    organisation: str
    base_url: str
    credential: str
    agreement: str

    def as_dict(self) -> dict[str, str]:
        return {
            "system": self.system,
            "organisation": self.organisation,
            "base_url": self.base_url,
            "credential": self.credential,
            "agreement": self.agreement,
        }


class RealClientStub:
    """Base of every not-yet-written real client.

    Subclasses set `integration` and call `self._pending(...)` from each method. The
    exception text names the endpoint and the credential, so the failure is a work item
    rather than a mystery.
    """

    integration: ClassVar[Integration]

    def _pending(self, operation: str, endpoint: str) -> NoReturn:
        """Refuse, naming exactly what is missing."""
        raise NotImplementedError(
            f"{type(self).__name__}.{operation} is not implemented. "
            f"It will call {self.integration.base_url}{endpoint} at "
            f"{self.integration.organisation}, which needs: {self.integration.credential}. "
            f"Blocked on: {self.integration.agreement}."
        )

    async def aclose(self) -> None:
        """Nothing is open. Present so a caller can close either client uniformly."""
        return None


# --------------------------------------------------------------------------------------
# HTTP plumbing
# --------------------------------------------------------------------------------------


class MockGovClient:
    """Shared HTTP behaviour for every client that talks to `gov-mock`.

    Deliberately has no retry. Retry policy belongs to the caller, which is the only layer
    that knows whether the call is idempotent and whether anybody is waiting for it.
    """

    system: ClassVar[str] = "unknown"

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        read_timeout: float = READ_TIMEOUT,
        connect_timeout: float = CONNECT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout)
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the transport, but only if this client opened it."""
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        """Outbound headers. The correlation ID crosses the boundary with the request."""
        correlation_id = get_correlation_id()
        return {CORRELATION_HEADER: correlation_id} if correlation_id else {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """One round trip, with every transport failure mapped to a typed error."""
        merged = self._headers() | (headers or {})
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                params=_clean_params(params),
                json=json,
                headers=merged,
            )
        except httpx.TimeoutException as error:
            _log.warning("gov_upstream_timeout", system=self.system, path=path)
            raise GovTimeout(self.system, f"{self.system} did not answer within its timeout") from (
                error
            )
        except httpx.TransportError as error:
            _log.warning(
                "gov_upstream_unreachable",
                system=self.system,
                path=path,
                error=type(error).__name__,
            )
            raise GovUpstreamError(self.system, f"{self.system} is unreachable") from error

        self._check_status(response, path)
        self._check_mock_header(response, path)
        return response

    def _check_status(self, response: httpx.Response, path: str) -> None:
        if response.status_code == 404:
            raise GovRecordNotFound(f"{self.system} has no record at {path}")
        if response.status_code in TIMEOUT_STATUSES:
            # A gateway that answers 408 or 504 is telling us the upstream timed out. It
            # is the same fact as our own read timeout expiring, reported by a different
            # party, and a caller deciding whether a retry is safe needs it to arrive as
            # the same error. Mapping it to a generic refusal would hide the one thing
            # that matters about it.
            _log.warning(
                "gov_upstream_timeout",
                system=self.system,
                path=path,
                status=response.status_code,
            )
            raise GovTimeout(
                self.system,
                f"{self.system} reported an upstream timeout ({response.status_code})",
            )
        if response.status_code >= 400:
            _log.warning(
                "gov_upstream_refused",
                system=self.system,
                path=path,
                status=response.status_code,
            )
            raise GovRefused(
                self.system,
                f"{self.system} refused the request",
                status=response.status_code,
            )

    def _check_mock_header(self, response: httpx.Response, path: str) -> None:
        """Refuse a response that does not admit to being a mock.

        The check is here, in the client, rather than trusted from the server: this is the
        one place that knows a mock was what we asked for. Without it, pointing
        `SARANA_GOV_MOCK_URL` at a real agency endpoint would work, and nobody would find
        out until real warnings appeared in a demo or synthetic rainfall reached something
        that mattered.
        """
        if response.headers.get(MOCK_HEADER) != MOCK_HEADER_VALUE:
            raise GovMalformedResponse(
                self.system,
                f"the response from {self.system} at {path} did not carry "
                f"{MOCK_HEADER}: {MOCK_HEADER_VALUE}. This client only speaks to the mock; "
                "check where SARANA_GOV_MOCK_URL points.",
            )

    async def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET a JSON document, verified to be a mock response."""
        response = await self._request("GET", path, params=params)
        return self._decode_json(response, path)

    async def _post_json(
        self,
        path: str,
        *,
        json: Any,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """POST a JSON document and decode the JSON answer."""
        response = await self._request("POST", path, params=params, json=json, headers=headers)
        return self._decode_json(response, path)

    async def _get_text(self, path: str, *, params: dict[str, Any] | None = None) -> str:
        """GET a non-JSON document — the Met Department's XML feeds.

        The mock marker is a header here, since there is no JSON envelope to carry it.
        """
        response = await self._request("GET", path, params=params)
        return response.text

    def _decode_json(self, response: httpx.Response, path: str) -> Any:
        body: Any
        try:
            body = response.json()
        except ValueError as error:
            # Malformed on purpose some of the time: real integrations return an HTML
            # error page or a truncated body, and code that has never met one breaks the
            # first time it does.
            raise GovMalformedResponse(
                self.system,
                f"{self.system} returned a body that is not JSON at {path}",
            ) from error

        if isinstance(body, dict) and body.get(MOCK_SOURCE_FIELD) != MOCK_SOURCE_VALUE:
            raise GovMalformedResponse(
                self.system,
                f"the response from {self.system} at {path} is missing "
                f'"{MOCK_SOURCE_FIELD}": "{MOCK_SOURCE_VALUE}"',
            )
        return body


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop unset query parameters.

    httpx serialises `None` as the string "None", which a real gateway would happily
    accept and then filter on.
    """
    if params is None:
        return None
    return {key: value for key, value in params.items() if value is not None}


# --------------------------------------------------------------------------------------
# XML
# --------------------------------------------------------------------------------------

# The Met Department really does serve XML. It arrives from outside the platform, so it is
# bounded before it is parsed — the same treatment `alerting_svc.domain.cap` gives an
# inbound CAP document, and for the same reason.
#
# A national warning bulletin is a few kilobytes; a megabyte is generous. The size cap is
# what stops a billion-laughs expansion, since ElementTree will happily expand internal
# entities. CPython's parser does not resolve *external* entities at all, so the XXE half
# of the usual XML risk does not apply.
MAX_XML_BYTES: Final = 1024 * 1024


def parse_xml(text: str, *, system: str) -> Element:
    """Parse an XML document from an external system, or raise `GovMalformedResponse`.

    Every caller in this package goes through here rather than reaching for ElementTree,
    so the bounds are applied once and cannot be forgotten by the next feed that is added.
    """
    if len(text.encode("utf-8")) > MAX_XML_BYTES:
        raise GovMalformedResponse(
            system,
            f"{system} returned an XML document over {MAX_XML_BYTES // 1024}KB; "
            "refused before parsing",
        )
    if "<!ENTITY" in text:
        # No legitimate warning bulletin declares entities, and refusing them outright is
        # simpler and safer than reasoning about how far one would expand.
        raise GovMalformedResponse(system, f"{system} returned XML declaring entities; refused")

    try:
        return ElementTree.fromstring(text)  # noqa: S314 - bounded and entity-free above
    except ElementTree.ParseError as error:
        raise GovMalformedResponse(system, f"{system} returned XML that is not well-formed") from (
            error
        )


def require_mock_xml(root: Element, *, system: str) -> Element:
    """Assert an XML root carries the mock marker, the way a JSON envelope does.

    XML has no envelope to hold `"source": "MOCK"`, so the root element carries
    `source="MOCK"` instead. The guarantee is the same one and is checked just as hard.
    """
    if root.get(MOCK_SOURCE_FIELD) != MOCK_SOURCE_VALUE:
        raise GovMalformedResponse(
            system,
            f'the XML from {system} is missing {MOCK_SOURCE_FIELD}="{MOCK_SOURCE_VALUE}" '
            "on its root element",
        )
    return root


def envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Stamp a mock JSON body with its source marker.

    Lives beside the client that verifies it, so the two can never be changed apart.
    `gov-mock` calls this on the way out; `MockGovClient` checks it on the way in.
    """
    return {MOCK_SOURCE_FIELD: MOCK_SOURCE_VALUE, **payload}
