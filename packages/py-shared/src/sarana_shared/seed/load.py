"""`python -m sarana_shared.seed.load` - load reference and scenario data.

Manifest-driven so the loader itself carries no knowledge of the schema. Each entry in
`data/seed/manifest.json` names a JSON file, the target table, and the conflict key:

    {
      "order": [
        {"file": "reference/province.json", "table": "reference.province", "key": ["code"]},
        {"file": "reference/district.json", "table": "reference.district", "key": ["code"]}
      ]
    }

Entries load in the order listed, so foreign keys resolve. Loading is idempotent -
`ON CONFLICT DO UPDATE` - so `make seed` can run repeatedly without a reset.

Every record is checked for trilingual completeness before it is written. A seed file
that would introduce a single-language citizen-facing record fails the load.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import MetaData, Table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from sarana_shared.db.session import DatabaseSettings, create_engine
from sarana_shared.domain.i18n_check import check_file

MANIFEST_NAME = "manifest.json"


class SeedEntry(BaseModel):
    """One file to load into one table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    table: str
    key: list[str] = Field(min_length=1, description="Columns forming the conflict target")


class SeedManifest(BaseModel):
    """The ordered load plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order: list[SeedEntry] = Field(default_factory=list)


async def load_entry(engine: AsyncEngine, root: Path, entry: SeedEntry) -> int:
    """Upsert one seed file. Returns the number of rows written."""
    path = root / entry.file
    if not path.exists():
        raise FileNotFoundError(f"seed manifest references a missing file: {path}")

    records: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    if not records:
        return 0

    schema_name, _, table_name = entry.table.rpartition(".")
    metadata = MetaData(schema=schema_name or None)

    async with engine.begin() as connection:
        table = await connection.run_sync(
            lambda sync_conn: Table(table_name, metadata, autoload_with=sync_conn)
        )
        statement = insert(table).values(records)
        updatable = {
            column.name: statement.excluded[column.name]
            for column in table.columns
            if column.name not in entry.key and column.name != "created_at"
        }
        statement = (
            statement.on_conflict_do_update(index_elements=entry.key, set_=updatable)
            if updatable
            else statement.on_conflict_do_nothing(index_elements=entry.key)
        )
        await connection.execute(statement)

    return len(records)


def validate_translations(root: Path, manifest: SeedManifest) -> list[str]:
    """Check every seed file for trilingual completeness before anything is written."""
    problems: list[str] = []
    for entry in manifest.order:
        path = root / entry.file
        if path.exists():
            problems.extend(check_file(path))
    return problems


async def run(root: Path, database_url: str) -> int:
    """Load every manifest entry in order. Returns a process exit code."""
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        sys.stdout.write(
            f"no {MANIFEST_NAME} under {root}; nothing to seed.\n"
            "Seed data and its manifest are produced by the simulation and seed-data "
            "build step.\n"
        )
        return 0

    manifest = SeedManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

    problems = validate_translations(root, manifest)
    if problems:
        sys.stderr.write("seed load aborted - incomplete translations:\n\n")
        for problem in problems:
            sys.stderr.write(f"  {problem}\n")
        return 1

    engine = create_engine(DatabaseSettings(url=database_url, application_name="sarana-seed"))
    try:
        total = 0
        for entry in manifest.order:
            written = await load_entry(engine, root, entry)
            total += written
            sys.stdout.write(f"  {entry.table:<32} {written:>6} rows\n")
        sys.stdout.write(f"seed complete: {total} rows across {len(manifest.order)} tables.\n")
    finally:
        await engine.dispose()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sarana-seed")
    parser.add_argument("--path", type=Path, default=Path("data/seed"))
    parser.add_argument(
        "--database-url",
        default=None,
        help="Async DSN. Defaults to SARANA_DATABASE_URL from the environment.",
    )
    args = parser.parse_args(argv)

    database_url = args.database_url
    if database_url is None:
        import os

        database_url = os.environ.get("SARANA_DATABASE_URL")
    if not database_url:
        sys.stderr.write("SARANA_DATABASE_URL is not set and --database-url was not given.\n")
        return 78

    return asyncio.run(run(args.path, database_url))


if __name__ == "__main__":
    raise SystemExit(main())
