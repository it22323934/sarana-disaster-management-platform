"""`python -m tools.cap_validate <files>` - the CAP gate from build file 09.

Two levels of checking, and the difference between them is stated plainly because it
matters:

**Structural (always).** Every CAP 1.2 rule this repository encodes: the namespace, the
required elements, one `<info>` per language with all three present and non-blank, the
controlled vocabularies. These are real rules from the standard.

**Schema (when you supply the XSD).** Pass `--xsd path/to/CAP-v1.2.xsd` and, with `lxml`
installed, the document is additionally validated against the official OASIS schema.

The XSD is **not vendored here.** It is an OASIS document, and writing one from memory to
make a green tick appear would be worse than having none - it would report a compliance
this repository cannot actually demonstrate. Download it from OASIS and point this at it
to close that gap.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alerting_svc.domain.cap import parse_problems


def validate_structure(path: Path) -> list[str]:
    """Structural problems in one document."""
    try:
        xml = path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"cannot read: {error}"]
    return parse_problems(xml)


def validate_against_xsd(paths: list[Path], xsd: Path) -> dict[Path, list[str]]:
    """Validate against a real XSD, if lxml is available.

    Returns a problem list per file. A missing lxml is reported once, as a problem with
    the request rather than with the documents.
    """
    try:
        from lxml import etree
    except ImportError:
        # A fresh list per path: dict.fromkeys would give every entry the same one, so
        # appending a problem to one document would append it to all of them.
        missing = (
            "--xsd was given but lxml is not installed; "
            "install it (uv add --dev lxml) to validate against the schema"
        )
        return {path: [missing] for path in paths}

    schema = etree.XMLSchema(etree.parse(str(xsd)))
    results: dict[Path, list[str]] = {}
    for path in paths:
        try:
            document = etree.parse(str(path))
        except etree.XMLSyntaxError as error:
            results[path] = [f"not well-formed: {error}"]
            continue
        if schema.validate(document):
            results[path] = []
        else:
            results[path] = [str(entry) for entry in schema.error_log]
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cap_validate")
    parser.add_argument("files", nargs="*", type=Path, help="CAP XML documents")
    parser.add_argument(
        "--xsd",
        type=Path,
        default=None,
        help="Official CAP 1.2 XSD. Not vendored; see this module's docstring.",
    )
    args = parser.parse_args(argv)

    paths = [path for path in args.files if path.is_file()]
    if not paths:
        sys.stdout.write("no CAP documents given; nothing to validate.\n")
        return 0

    failures = 0
    schema_results = validate_against_xsd(paths, args.xsd) if args.xsd is not None else {}

    for path in paths:
        problems = validate_structure(path)
        problems += schema_results.get(path, [])
        if problems:
            failures += 1
            sys.stderr.write(f"FAIL {path}\n")
            for problem in problems:
                sys.stderr.write(f"       {problem}\n")
        else:
            sys.stdout.write(f"ok   {path}\n")

    if args.xsd is None:
        sys.stdout.write(
            "\nStructural checks only. The official CAP 1.2 XSD is not vendored in this "
            "repository; pass --xsd to validate against it.\n"
        )

    if failures:
        sys.stderr.write(f"\n{failures} of {len(paths)} document(s) failed.\n")
        return 1

    sys.stdout.write(f"\n{len(paths)} document(s) valid.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
