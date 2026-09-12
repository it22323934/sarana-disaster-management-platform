"""`python -m tools.sms_segment_check` - the SMS segment gate from build file 14.

Every seeded alert template, rendered in all three languages with worst-case parameter
values, must fit inside two SMS segments. Exits 0 when they all do and 1 naming the ones
that do not.

## Why this is a release gate and not a metric

Sinhala and Tamil are UCS-2 on the wire, so a segment holds 70 characters where the English
version gets 160 - and 67 per part once the message is concatenated. A template that reads
comfortably in English can be three segments in Tamil, which is three times the cost, three
times the queue on a congested gateway during exactly the event that congested it, and
three parts that can arrive out of order or not at all.

The community reading the Tamil version is then the one whose warning arrives last and
incomplete. That is the Ditwah failure - the 28 Nov 2025 press conference was Sinhala and
English only - arriving through a billing detail instead of through a decision, and it is
the kind of thing nobody notices until an after-action review, because in testing every
message is short.

## Worst case, not typical case

Templates are checked with the **longest** value each parameter can take, drawn from the
seeded reference data where it exists. A check that passed with "Kandy" and failed in
production with a real division name would be a check that made things worse by being
reassuring.

## On the path in the build file

Build file 14's definition of done names `data/seed/alert_templates.yaml`. This repository
seeds templates as JSON at `data/seed/reference/alert_template.json`, generated from
`tools/seed/templates.py`, and there is no YAML anywhere in the seed. The default below is
the file that actually exists; a path argument overrides it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

from sarana_shared.domain import sms
from sarana_shared.domain.localised import REQUIRED_LOCALES

DEFAULT_TEMPLATES: Final = Path("data/seed/reference/alert_template.json")
DEFAULT_REFERENCE: Final = Path("data/seed/reference")

# The parameters a template may carry, and where a worst-case value for each comes from.
#
# The three that name a place are measured from the seeded reference data, so the check
# tracks the real names rather than a guess about them. The rest are formats this platform
# controls: a time is five characters because that is how the renderer writes one, and a
# shelter or a distribution point is a building name, for which a generous stand-in is used
# because no seeded list of them exists yet.
FALLBACK_VALUES: Final[dict[str, str]] = {
    "shelter_name": "Mahanuwara Maha Vidyalaya Community Hall",
    "deadline_time": "18:30",
    "effective_time": "18:30",
    "water_level_m": "12.5",
    "road_name": "Colombo-Kandy A1 Highway",
    "distribution_point": "Pradeshiya Sabha Grounds",
    "hazard_name": "Storm Surge",
}

# Which reference file supplies the longest name for which parameter.
NAME_SOURCES: Final[dict[str, str]] = {
    "gn_division_name": "gn_division.json",
    "ds_division_name": "ds_division.json",
    "district_name": "district.json",
}


def longest_names(reference: Path) -> dict[str, dict[str, str]]:
    """The longest name in each reference file, per language.

    Per language rather than one overall, because the longest Sinhala name and the longest
    Tamil name are usually different rows and a template is rendered in both.
    """
    found: dict[str, dict[str, str]] = {}
    for parameter, filename in NAME_SOURCES.items():
        path = reference / filename
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        per_language: dict[str, str] = {}
        for locale in REQUIRED_LOCALES:
            code = locale.value
            names = [str(row.get("name", {}).get(code, "")) for row in rows]
            if names:
                per_language[code] = max(names, key=len)
        if per_language:
            found[parameter] = per_language
    return found


def worst_case_values(reference: Path, language: str) -> dict[str, str]:
    """Every parameter, filled with the longest plausible value in one language."""
    values = dict(FALLBACK_VALUES)
    for parameter, per_language in longest_names(reference).items():
        values[parameter] = per_language.get(language) or values.get(parameter, parameter)
    for parameter in NAME_SOURCES:
        values.setdefault(parameter, "Thirukkovil Divisional Secretariat Division")
    return values


def render(body: str, values: dict[str, str]) -> str:
    """Substitute every parameter the body names."""
    text = body
    for name, value in values.items():
        text = text.replace("{" + name + "}", value)
    return text


def load_templates(path: Path) -> list[dict[str, Any]]:
    """The templates to check.

    Raises:
        FileNotFoundError: naming the path. A gate that reports zero templates as a pass is
            one that goes green the day somebody moves the seed.
    """
    if not path.exists():
        raise FileNotFoundError(f"No template seed at {path}")

    rows = json.loads(path.read_text(encoding="utf-8"))
    if not rows:
        raise FileNotFoundError(f"{path} holds no templates")
    return list(rows)


def check(
    templates: list[dict[str, Any]], *, reference: Path, max_segments: int = sms.MAX_SEGMENTS
) -> list[tuple[str, str, sms.SegmentCount]]:
    """Every (template, language) pair, with what it costs on the wire.

    Returns all of them, not only the failures: the report prints the tightest passing
    templates too, because a template one character under the limit is one an operator
    breaks with the next place name.
    """
    measured: list[tuple[str, str, sms.SegmentCount]] = []
    for template in templates:
        code = str(template.get("code", "?"))
        body = template.get("body", {})
        for locale in REQUIRED_LOCALES:
            language = locale.value
            values = worst_case_values(reference, language)
            text = render(str(body.get(language, "")), values)
            measured.append((code, language, sms.count(text, max_segments=max_segments)))
    return measured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.sms_segment_check",
        description="Check every seeded alert template fits inside two SMS segments in "
        "all three languages, using worst-case parameter values.",
    )
    parser.add_argument("templates", type=Path, nargs="?", default=DEFAULT_TEMPLATES)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--max-segments", type=int, default=sms.MAX_SEGMENTS)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every template, not only the failures and the tightest passes.",
    )
    args = parser.parse_args(argv)

    try:
        templates = load_templates(args.templates)
    except (FileNotFoundError, json.JSONDecodeError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 2

    measured = check(templates, reference=args.reference, max_segments=args.max_segments)
    failures = [row for row in measured if row[2].segments > args.max_segments]

    sys.stdout.write(
        f"{len(templates)} templates x {len(REQUIRED_LOCALES)} languages, "
        f"worst-case parameters, limit {args.max_segments} segments\n"
    )

    if args.verbose:
        for code, language, counted in measured:
            sys.stdout.write(f"  {code:26} {language}  {counted.as_sentence()}\n")
    else:
        # The five tightest passes. Somebody reading this wants to know what is about to
        # break, not a list of thirty-six things that are fine.
        tightest = sorted(
            (row for row in measured if row not in failures), key=lambda row: row[2].headroom
        )[:5]
        sys.stdout.write("tightest passing:\n")
        for code, language, counted in tightest:
            sys.stdout.write(f"  {code:26} {language}  {counted.as_sentence()}\n")

    if not failures:
        sys.stdout.write(f"OK: every rendering fits in {args.max_segments} segments\n")
        return 0

    sys.stderr.write(f"\n{len(failures)} rendering(s) over the limit:\n")
    for code, language, counted in failures:
        sys.stderr.write(f"  {code} [{language}]: {counted.as_sentence()}\n")
    sys.stderr.write(
        "\nShorten the template. A Sinhala or Tamil warning over two segments costs an "
        "extra part on the gateway that is already congested by the event, and the "
        "community reading that language is the one whose warning arrives incomplete.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
