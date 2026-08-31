"""CAP 1.2 alert documents.

Real OASIS Common Alerting Protocol XML, not CAP-shaped JSON. The point is that a third
party - a broadcaster, a neighbouring country's warning system, Google Public Alerts -
can consume what this produces without SARANA writing them an adapter.

**On the XSD.** The build brief says to validate against the official CAP 1.2 XSD before
dispatch. That schema is an OASIS document this repository does not vendor, so
`validate()` below implements the standard's structural rules directly and
`tools/cap_validate.py` will additionally run a real XSD when one is supplied.

Writing an XSD from memory and calling it "the official CAP 1.2 schema" would be worse
than having none: it would report compliance this code cannot actually demonstrate. What
is here is honest about which rules it checks, and every one of them is a rule the
standard states.

**This lives in the shared package rather than in alerting-svc**, which is where it was
written in file 09. The warning agent (file 14) validates the document *before* it asks
alerting-svc to send it, so that a CAP problem is caught while a graph can still route it
to an operator rather than after a dispatch call has been made. Two services needing the
same document meant either one implementation here or two implementations drifting apart,
and two CAP validators disagreeing about whether a warning is dispatchable is not a
disagreement anybody would find until it mattered. `alerting_svc.domain.cap` re-exports
this module, so file 09's call sites are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Final
from xml.etree import ElementTree

from sarana_shared.domain.localised import REQUIRED_LOCALES

CAP_NAMESPACE: Final = "urn:oasis:names:tc:emergency:cap:1.2"

# Sri Lanka Standard Time. CAP requires an explicit offset and forbids "Z" being used as a
# stand-in for local time, because a warning's timestamp is read by people deciding whether
# it is still current.
COLOMBO_OFFSET: Final = timezone(timedelta(hours=5, minutes=30))

# CAP consumers choke above a few hundred polygon points, and the brief caps it at 100.
MAX_POLYGON_POINTS: Final = 100

GEOCODE_VALUE_NAME: Final = "LK_GN_CODE"

MSG_TYPES: Final[tuple[str, ...]] = ("Alert", "Update", "Cancel", "Ack", "Error")
STATUSES: Final[tuple[str, ...]] = ("Actual", "Exercise", "System", "Test", "Draft")
SCOPES: Final[tuple[str, ...]] = ("Public", "Restricted", "Private")

# CAP's own vocabularies, capitalised as the standard writes them.
SEVERITIES: Final[tuple[str, ...]] = ("Extreme", "Severe", "Moderate", "Minor", "Unknown")
URGENCIES: Final[tuple[str, ...]] = ("Immediate", "Expected", "Future", "Past", "Unknown")
CERTAINTIES: Final[tuple[str, ...]] = ("Observed", "Likely", "Possible", "Unlikely", "Unknown")

# CAP language codes for the three SARANA serves.
CAP_LANGUAGES: Final[dict[str, str]] = {"si": "si-LK", "ta": "ta-LK", "en": "en-LK"}


def cap_case(value: str) -> str:
    """A SARANA upper-case vocabulary value as CAP writes it.

    The schema stores `EXTREME` and `STORM_SURGE`; CAP wants `Extreme` and `Storm surge`.
    Converted at the boundary rather than stored twice, so the two can never disagree —
    and in one function rather than one per service, because a second copy is how
    `STORM_SURGE` ends up rendered as `Storm_surge` in whichever service was written later.
    """
    return value.replace("_", " ").capitalize()


class CapInvalid(ValueError):
    """The document does not satisfy CAP 1.2.

    Raised before dispatch and never caught into a warning. A schema-invalid alert is
    never sent, full stop - a consumer that cannot parse it is a broadcaster that does not
    broadcast it.
    """

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True, slots=True)
class Area:
    """The targeted area, as both a polygon and the division codes it covers.

    Both, not either. The polygon is what a mapping consumer draws; the geocodes are what a
    system that already knows Sri Lankan divisions matches on, and they survive the
    simplification that the polygon does not.
    """

    polygon: list[tuple[float, float]] = field(default_factory=list)
    gn_codes: list[str] = field(default_factory=list)
    description: str = "Sri Lanka"

    def simplified(self, limit: int = MAX_POLYGON_POINTS) -> list[tuple[float, float]]:
        """The polygon reduced to at most `limit` points, keeping it closed.

        Even sampling rather than Douglas-Peucker: this runs on a warning path and the
        geocodes carry the authoritative extent anyway, so a cheap, predictable reduction
        is the right trade.
        """
        if len(self.polygon) <= limit:
            return list(self.polygon)

        # Keep the first and last point so the ring still closes.
        interior = self.polygon[1:-1]
        step = max(1, len(interior) // (limit - 2))
        sampled = interior[::step][: limit - 2]
        return [self.polygon[0], *sampled, self.polygon[-1]]


@dataclass(frozen=True, slots=True)
class CapAlert:
    """Everything one CAP document needs.

    The three localised fields are dictionaries keyed by locale and all three are
    required. That is checked here rather than trusted, because this is the last place
    before a warning leaves the platform.
    """

    identifier: str
    sender: str
    sent: datetime
    msg_type: str
    status: str
    scope: str

    event: str
    category: str
    severity: str
    urgency: str
    certainty: str

    headline: dict[str, str]
    description: dict[str, str]
    instruction: dict[str, str]

    effective: datetime
    expires: datetime
    area: Area

    references: str | None = None


def _rfc3339(moment: datetime) -> str:
    """CAP timestamps in Colombo local time with an explicit offset."""
    return (
        moment.astimezone(COLOMBO_OFFSET).strftime("%Y-%m-%dT%H:%M:%S%z")[:-2]
        + ":"
        + (moment.astimezone(COLOMBO_OFFSET).strftime("%z")[-2:])
    )


def build(alert: CapAlert) -> ElementTree.Element:
    """Build the CAP document tree.

    One `<alert>` with one `<info>` per language, each carrying its own headline,
    description and instruction and repeating the shared `<area>`. CAP has no way to share
    an area across info blocks, so it is repeated rather than referenced.
    """
    ElementTree.register_namespace("", CAP_NAMESPACE)
    root = ElementTree.Element(f"{{{CAP_NAMESPACE}}}alert")

    def child(parent: ElementTree.Element, tag: str, text: str) -> ElementTree.Element:
        element = ElementTree.SubElement(parent, f"{{{CAP_NAMESPACE}}}{tag}")
        element.text = text
        return element

    child(root, "identifier", alert.identifier)
    child(root, "sender", alert.sender)
    child(root, "sent", _rfc3339(alert.sent))
    child(root, "status", alert.status)
    child(root, "msgType", alert.msg_type)
    child(root, "scope", alert.scope)
    if alert.references:
        child(root, "references", alert.references)

    for locale in REQUIRED_LOCALES:
        code = locale.value
        info = ElementTree.SubElement(root, f"{{{CAP_NAMESPACE}}}info")
        child(info, "language", CAP_LANGUAGES[code])
        child(info, "category", alert.category)
        child(info, "event", alert.event)
        child(info, "urgency", alert.urgency)
        child(info, "severity", alert.severity)
        child(info, "certainty", alert.certainty)
        child(info, "effective", _rfc3339(alert.effective))
        child(info, "expires", _rfc3339(alert.expires))
        child(info, "headline", alert.headline.get(code, ""))
        child(info, "description", alert.description.get(code, ""))
        child(info, "instruction", alert.instruction.get(code, ""))

        area = ElementTree.SubElement(info, f"{{{CAP_NAMESPACE}}}area")
        child(area, "areaDesc", alert.area.description)
        points = alert.area.simplified()
        if points:
            # CAP polygons are "lat,lon lat,lon ...", latitude first.
            child(
                area,
                "polygon",
                " ".join(f"{lat:.5f},{lon:.5f}" for lon, lat in points),
            )
        for gn_code in alert.area.gn_codes:
            geocode = ElementTree.SubElement(area, f"{{{CAP_NAMESPACE}}}geocode")
            child(geocode, "valueName", GEOCODE_VALUE_NAME)
            child(geocode, "value", gn_code)

    return root


def to_xml(alert: CapAlert) -> str:
    """The CAP document as a string, ready to serve or store."""
    root = build(alert)
    ElementTree.indent(root, space="  ")
    body = ElementTree.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body


def validate(alert: CapAlert) -> None:
    """Check every CAP 1.2 rule this module can check, or refuse.

    Raises:
        CapInvalid: with every problem found, not just the first. An operator fixing a
            template wants the whole list.
    """
    problems: list[str] = []

    if not alert.identifier.strip():
        problems.append("identifier is required and must be globally unique")
    if " " in alert.identifier:
        problems.append("identifier must not contain spaces (CAP 1.2 §3.2.1)")
    if not alert.sender.strip():
        problems.append("sender is required")
    if alert.msg_type not in MSG_TYPES:
        problems.append(f"msgType must be one of {', '.join(MSG_TYPES)}")
    if alert.status not in STATUSES:
        problems.append(f"status must be one of {', '.join(STATUSES)}")
    if alert.scope not in SCOPES:
        problems.append(f"scope must be one of {', '.join(SCOPES)}")
    if alert.severity not in SEVERITIES:
        problems.append(f"severity must be one of {', '.join(SEVERITIES)}")
    if alert.urgency not in URGENCIES:
        problems.append(f"urgency must be one of {', '.join(URGENCIES)}")
    if alert.certainty not in CERTAINTIES:
        problems.append(f"certainty must be one of {', '.join(CERTAINTIES)}")

    # A Cancel or Update must say what it supersedes, or a consumer cannot apply it.
    if alert.msg_type in {"Update", "Cancel"} and not alert.references:
        problems.append(
            f"a {alert.msg_type} message must carry references to the alert it replaces"
        )

    if alert.expires <= alert.effective:
        problems.append("expires must be after effective")

    # The trilingual gate, at the last possible moment before dispatch.
    for name, value in (
        ("headline", alert.headline),
        ("description", alert.description),
        ("instruction", alert.instruction),
    ):
        for locale in REQUIRED_LOCALES:
            text = value.get(locale.value, "")
            if not text or not text.strip():
                problems.append(
                    f"{name} is missing or blank in {locale.value}; a life-safety message "
                    "is never dispatched in fewer than three languages"
                )

    if not alert.area.gn_codes and not alert.area.polygon:
        problems.append("area must carry a polygon, geocodes, or both")

    if len(alert.area.simplified()) > MAX_POLYGON_POINTS:
        problems.append(f"polygon exceeds {MAX_POLYGON_POINTS} points after simplification")

    if problems:
        raise CapInvalid(problems)


# CAP documents can arrive from outside - a feed this platform ingests, or a file an
# operator points the CLI at - so parsing is bounded before it starts.
#
# A CAP alert for the whole country is a few hundred kilobytes; a megabyte is generous.
# The cap is what stops a billion-laughs expansion, since ElementTree will happily expand
# internal entities. CPython's parser does not resolve *external* entities at all, so the
# XXE half of the usual XML risk does not apply here.
MAX_DOCUMENT_BYTES: Final = 1024 * 1024


def parse_problems(xml: str) -> list[str]:
    """Structural problems in an already-serialised CAP document.

    Used by the CLI gate over stored artefacts, where the original `CapAlert` is gone.
    """
    problems: list[str] = []

    if len(xml.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        return [
            f"document exceeds {MAX_DOCUMENT_BYTES // 1024}KB; refused before parsing. "
            "A CAP alert covering the whole country is far smaller than this."
        ]
    if "<!ENTITY" in xml:
        # No legitimate CAP document declares entities, and refusing them outright is
        # simpler and safer than reasoning about how far one would expand.
        return ["document declares XML entities; refused"]

    try:
        root = ElementTree.fromstring(xml)  # noqa: S314 - bounded and entity-free above
    except ElementTree.ParseError as error:
        return [f"not well-formed XML: {error}"]

    if root.tag != f"{{{CAP_NAMESPACE}}}alert":
        problems.append(f"root element must be {{{CAP_NAMESPACE}}}alert, got {root.tag}")

    infos = root.findall(f"{{{CAP_NAMESPACE}}}info")
    if len(infos) != len(REQUIRED_LOCALES):
        problems.append(
            f"expected one <info> per language ({len(REQUIRED_LOCALES)}), found {len(infos)}"
        )

    languages = {(info.findtext(f"{{{CAP_NAMESPACE}}}language") or "").strip() for info in infos}
    expected = set(CAP_LANGUAGES.values())
    if languages != expected:
        problems.append(f"languages must be exactly {sorted(expected)}, found {sorted(languages)}")

    for info in infos:
        language = info.findtext(f"{{{CAP_NAMESPACE}}}language") or "?"
        for tag in ("headline", "description", "instruction"):
            text = info.findtext(f"{{{CAP_NAMESPACE}}}{tag}")
            if not text or not text.strip():
                problems.append(f"<{tag}> is empty for {language}")

    for required in ("identifier", "sender", "sent", "status", "msgType", "scope"):
        if not (root.findtext(f"{{{CAP_NAMESPACE}}}{required}") or "").strip():
            problems.append(f"<{required}> is required")

    return problems
