"""The inbound simulator: a page where somebody plays the part of a citizen.

Every other route in this service is *outbound* — the platform asking a government system
for something. This one is the opposite: a person with a feature phone sending an SMS or
dialling a USSD code into SARANA. Without it the demo is entirely dashboards, and the
platform's whole claim is that it works for people who do not have a smartphone.

Two things about how it is wired:

**The service token never reaches the browser.** The page posts to gov-mock, and gov-mock
forwards to incident-svc with `SARANA_INCIDENT_SERVICE_TOKEN`. Putting a long-lived
`INCIDENT_WRITE` credential into a page anybody at a demo can open would be handing out
the ability to file reports as the telco gateway.

**The number is hashed here, with the platform's own key.** incident-svc identifies a
sender by an HMAC of their number and never sees the number itself. The simulator does the
same hashing, with the same key, so a number typed twice is recognised as the same person —
which is what makes a follow-up SMS attach to the report it belongs to.

The page is served from a string rather than a template directory. It is one page with no
build step, and a Jinja environment plus a templates folder for it would be more machinery
than page.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Final

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from gov_mock.api.deps import SimulatedNowDep, StateDep, mock_json
from gov_mock.state import InboundMessage, MockState
from sarana_shared.adapters.gov.base import MOCK_HEADER, MOCK_HEADER_VALUE

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/telco/sim", tags=["sim"])

FORWARD_TIMEOUT: Final = 10.0

LANGUAGES: Final[tuple[tuple[str, str], ...]] = (
    ("si", "සිංහල"),
    ("ta", "தமிழ்"),
    ("en", "English"),
)

# Prefilled examples, one per language. A demoer should not have to invent an emergency in
# a language they do not read, and a blank box in front of an audience is a long five
# seconds.
EXAMPLES: Final[dict[str, str]] = {
    "si": "ගංවතුර මගේ ගමේ. පවුල් 4ක් සිරවී ඇත.",
    "ta": "வெள்ளம். 4 குடும்பங்கள் சிக்கியுள்ளன.",
    "en": "FLOOD in our village, 4 families trapped, water rising fast",
}


class InboundSmsIn(BaseModel):
    """An SMS sent from the simulator page."""

    model_config = ConfigDict(extra="forbid")

    msisdn: str = Field(min_length=6, max_length=20)
    language: str = Field(default="en", min_length=2, max_length=2)
    body: str = Field(min_length=1, max_length=1600)


class InboundUssdIn(BaseModel):
    """One turn of a USSD session from the simulator page."""

    model_config = ConfigDict(extra="forbid")

    msisdn: str = Field(min_length=6, max_length=20)
    language: str = Field(default="en", min_length=2, max_length=2)
    session_id: str = Field(min_length=1, max_length=64)
    choice: str = Field(default="", max_length=8)
    step: str | None = None
    incident_type: str | None = None
    people_at_risk: int | None = None


async def _forward(request: Request, path: str, payload: dict[str, Any]) -> tuple[int, Any]:
    """POST into incident-svc with the service credential.

    Returns the status and the decoded body rather than raising, because the simulator's
    job is to *show* what happened — including a 401 from a missing service token, which is
    the failure a demoer is most likely to hit and the one an exception would hide behind a
    stack trace.
    """
    settings = request.app.state.settings
    token = settings.incident_service_token
    if not token:
        return 0, {
            "error": (
                "SARANA_INCIDENT_SERVICE_TOKEN is not set, so the simulator cannot reach "
                "incident-svc. Mint one with `uv run python tools/seed/service_token.py`."
            )
        }

    url = f"{settings.incident_svc_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=FORWARD_TIMEOUT) as client:
            response = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
    except (httpx.TimeoutException, httpx.TransportError) as error:
        _log.warning("sim_forward_failed", path=path, error=type(error).__name__)
        return 0, {"error": f"incident-svc is unreachable at {url}"}

    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"body": response.text[:500]}


def _record(
    state: MockState,
    now: datetime,
    *,
    msisdn: str,
    language: str,
    channel: str,
    body: str,
    path: str,
    status_code: int,
    response: Any,
) -> None:
    """Keep what was sent, so the page can show a history."""
    state.inbound.append(
        InboundMessage(
            received_at=now,
            # The number is kept only in this in-memory demo log, and only because a
            # demoer needs to see which handset they were pretending to be. It never
            # leaves the process and never reaches the platform, which sees the hash.
            msisdn=msisdn,
            language=language,
            channel=channel,
            body=body,
            forwarded_to=path,
            status_code=status_code or None,
            response_excerpt=str(response)[:400],
        )
    )


@router.post("/sms", summary="Send an SMS into the platform")
async def send_sms(
    payload: InboundSmsIn, request: Request, state: StateDep, now: SimulatedNowDep
) -> Any:
    """Forward a simulated citizen SMS to incident-svc."""
    hasher = request.app.state.settings.keyed_hasher()
    path = "/internal/v1/channels/sms/inbound"
    status_code, body = await _forward(
        request,
        path,
        {"sender_hash": hasher.hash(payload.msisdn), "body": payload.body},
    )
    _record(
        state,
        now,
        msisdn=payload.msisdn,
        language=payload.language,
        channel="SMS",
        body=payload.body,
        path=path,
        status_code=status_code,
        response=body,
    )
    return mock_json({"forwarded": {"status": status_code, "response": body}})


@router.post("/ussd", summary="Send one USSD turn into the platform")
async def send_ussd(
    payload: InboundUssdIn, request: Request, state: StateDep, now: SimulatedNowDep
) -> Any:
    """Forward one turn of a simulated USSD session to incident-svc."""
    hasher = request.app.state.settings.keyed_hasher()
    path = "/internal/v1/channels/ussd/session"
    turn = {
        "sender_hash": hasher.hash(payload.msisdn),
        "session_id": payload.session_id,
        "choice": payload.choice,
        "step": payload.step,
        "language": payload.language,
        "incident_type": payload.incident_type,
        "people_at_risk": payload.people_at_risk,
    }
    status_code, body = await _forward(request, path, turn)
    _record(
        state,
        now,
        msisdn=payload.msisdn,
        language=payload.language,
        channel="USSD",
        body=f"choice={payload.choice or '(start)'} step={payload.step or '(start)'}",
        path=path,
        status_code=status_code,
        response=body,
    )
    return mock_json({"forwarded": {"status": status_code, "response": body}})


@router.get("/history", summary="What the simulator has sent")
def history(state: StateDep) -> Any:
    """Everything sent from the page since the last scenario load."""
    return mock_json(
        {
            "inbound": [
                {
                    "received_at": entry.received_at.isoformat(),
                    "msisdn": entry.msisdn,
                    "language": entry.language,
                    "channel": entry.channel,
                    "body": entry.body,
                    "forwarded_to": entry.forwarded_to,
                    "status_code": entry.status_code,
                    "response_excerpt": entry.response_excerpt,
                }
                for entry in reversed(state.inbound[-50:])
            ]
        }
    )


@router.get("", summary="The inbound simulator page", include_in_schema=False)
def page() -> HTMLResponse:
    """The demo page itself."""
    return HTMLResponse(content=_PAGE, headers={MOCK_HEADER: MOCK_HEADER_VALUE})


_TEMPLATE: Final = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SARANA - inbound simulator</title>
<style>
  :root { color-scheme: light dark; --line: #8883; }
  body { font: 15px/1.5 system-ui, sans-serif; margin: 0; padding: 2rem 1rem; }
  main { max-width: 46rem; margin: 0 auto; }
  h1 { font-size: 1.3rem; margin: 0 0 .25rem; }
  h2 { font-size: 1rem; }
  .lede { opacity: .75; margin: 0 0 1.5rem; }
  .banner { border: 1px solid var(--line); border-left: 3px solid #c60;
            padding: .6rem .8rem; margin-bottom: 1.5rem; font-size: .9rem; }
  fieldset { border: 1px solid var(--line); border-radius: 6px;
             padding: 1rem; margin: 0 0 1.25rem; }
  legend { padding: 0 .4rem; font-weight: 600; }
  label { display: block; margin: .6rem 0 .2rem; font-size: .85rem; opacity: .8; }
  input, select, textarea, button { font: inherit; width: 100%; box-sizing: border-box;
    padding: .5rem; border: 1px solid var(--line); border-radius: 4px;
    background: transparent; color: inherit; }
  textarea { min-height: 5rem; resize: vertical; }
  button { cursor: pointer; margin-top: .8rem; font-weight: 600; }
  .row { display: flex; gap: .75rem; flex-wrap: wrap; }
  .row > * { flex: 1 1 12rem; }
  pre { border: 1px solid var(--line); border-radius: 4px; padding: .7rem;
        overflow-x: auto; font-size: .8rem; white-space: pre-wrap; }
  .entry { border-top: 1px solid var(--line); padding: .6rem 0; font-size: .85rem; }
  .ok { color: #2a7; } .bad { color: #c44; }
</style>
</head>
<body>
<main>
  <h1>SARANA inbound simulator</h1>
  <p class="lede">Play the part of a citizen with a feature phone.</p>

  <p class="banner"><strong>Mock.</strong> Nothing here dials a real number or reaches a
  real handset. Your number is hashed on this page's server before it goes anywhere; the
  platform never sees it.</p>

  <fieldset>
    <legend>Handset</legend>
    <div class="row">
      <div>
        <label for="msisdn">Mobile number</label>
        <input id="msisdn" value="+94771234567" autocomplete="off">
      </div>
      <div>
        <label for="language">Language</label>
        <select id="language">__LANG_OPTIONS__</select>
      </div>
    </div>
  </fieldset>

  <fieldset>
    <legend>Send an SMS</legend>
    <label for="body">Message</label>
    <textarea id="body"></textarea>
    <button id="send-sms">Send SMS</button>
  </fieldset>

  <fieldset>
    <legend>USSD session</legend>
    <p class="lede" style="margin:.2rem 0 0">Send a blank keypress to dial in, then one
    keypress per turn. The step carries forward on its own.</p>
    <div class="row">
      <div>
        <label for="choice">Keypress</label>
        <input id="choice" placeholder="1" autocomplete="off">
      </div>
      <div>
        <label for="step">Current step</label>
        <input id="step" placeholder="(blank to start)" autocomplete="off">
      </div>
    </div>
    <button id="send-ussd">Send USSD turn</button>
    <pre id="ussd-reply">Dial to begin.</pre>
  </fieldset>

  <h2>Sent</h2>
  <div id="history"></div>
</main>

<script>
const examples = __EXAMPLES__;
const $ = (id) => document.getElementById(id);
const escape = (text) => String(text).replace(/[&<>]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

function fillExample() {
  $("body").value = examples[$("language").value] || "";
}
$("language").addEventListener("change", fillExample);
fillExample();

async function post(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}

$("send-sms").addEventListener("click", async () => {
  await post("/telco/sim/sms", {
    msisdn: $("msisdn").value,
    language: $("language").value,
    body: $("body").value,
  });
  await refresh();
});

$("send-ussd").addEventListener("click", async () => {
  const step = $("step").value.trim();
  const result = await post("/telco/sim/ussd", {
    msisdn: $("msisdn").value,
    language: $("language").value,
    session_id: "sim-" + $("msisdn").value,
    choice: $("choice").value.trim(),
    step: step === "" ? null : step,
  });
  const reply = (result.forwarded || {}).response || {};
  $("ussd-reply").textContent = reply.text || JSON.stringify(reply, null, 2);
  // Carry the session forward so the next keypress continues where this one left off.
  if (reply.step) { $("step").value = reply.step; }
  $("choice").value = "";
  await refresh();
});

async function refresh() {
  const data = await (await fetch("/telco/sim/history")).json();
  const rows = (data.inbound || []).map((entry) => {
    const ok = entry.status_code && entry.status_code < 400;
    return `<div class="entry">
      <strong>${escape(entry.channel)}</strong> ${escape(entry.msisdn)}
      (${escape(entry.language)})
      <span class="${ok ? "ok" : "bad"}">${escape(entry.status_code || "unreachable")}</span>
      <div>${escape(entry.body)}</div>
      <div style="opacity:.65">${escape(entry.response_excerpt)}</div>
    </div>`;
  });
  $("history").innerHTML = rows.join("") || "<p class='lede'>Nothing sent yet.</p>";
}
refresh();
</script>
</body>
</html>
"""


_LANGUAGE_OPTIONS: Final = "".join(
    f'<option value="{code}">{label}</option>' for code, label in LANGUAGES
)

# Built by token replacement rather than an f-string. The page is mostly CSS and
# JavaScript, both of which are made of braces; an f-string would need every one of them
# doubled, and the first missed pair is a page that renders as a syntax error in front of
# an audience.
_PAGE: Final = _TEMPLATE.replace("__LANG_OPTIONS__", _LANGUAGE_OPTIONS).replace(
    "__EXAMPLES__", json.dumps(EXAMPLES, ensure_ascii=False)
)
