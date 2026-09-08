/**
 * The on-device schema, and the migrations that build it.
 *
 * The device database is the source of truth for the user (file 22). Every write lands
 * here first and the UI reads it back immediately; sync is a background reconciliation
 * that happens afterwards and may never happen at all. A GN officer who taps Save and
 * waits for a spinner during a flood has been failed by the design.
 *
 * Migrations are a forward-only list. `PRAGMA user_version` is the position, so a device
 * upgraded from an older build runs only what it has not run. There is no down
 * migration: a field device that has to roll back a schema reinstalls.
 */

import type { Database } from './types.js';

/**
 * Statements run on every open, before any migration.
 *
 * WAL is not optional. Without it a background sync writing the operation log blocks the
 * UI thread reading it, which shows up as the app freezing while the officer types.
 */
export const PRAGMAS: readonly string[] = [
  'PRAGMA journal_mode = WAL',
  // NORMAL rather than FULL: a power cut can lose the last transaction, and the operation
  // log is designed to be replayed, so the cost of that is a re-sync rather than lost data.
  'PRAGMA synchronous = NORMAL',
  'PRAGMA foreign_keys = ON',
  'PRAGMA busy_timeout = 5000',
];

/**
 * The append-only client operation log (ADR-006).
 *
 * `status` carries one value the brief does not list: `blocked`. The server's sync
 * contract (`ledger_svc.domain.sync.OperationStatus`) reports an operation held behind a
 * gap as `blocked`, and calling that a conflict on the device would send the officer
 * looking for a disagreement that does not exist. Where the brief and the server
 * vocabulary differ, the server wins.
 */
const OPERATION_LOG = `
CREATE TABLE IF NOT EXISTS operation_log (
  client_operation_id TEXT PRIMARY KEY,
  seq                 INTEGER NOT NULL,
  entity_type         TEXT NOT NULL,
  entity_local_id     TEXT NOT NULL,
  op                  TEXT NOT NULL CHECK (op IN ('create', 'update')),
  payload             TEXT NOT NULL,
  created_at          TEXT NOT NULL,
  synced_at           TEXT,
  server_id           TEXT,
  status              TEXT NOT NULL CHECK (
    status IN ('pending', 'syncing', 'synced', 'blocked', 'conflict', 'failed')
  ),
  attempt_count       INTEGER NOT NULL DEFAULT 0,
  last_error          TEXT,
  conflict_detail     TEXT
)`;

/**
 * One row. The device's identity and its sync cursor.
 *
 * `next_seq` is allocated here rather than computed as `MAX(seq) + 1`, because the log is
 * purged after 30 days and a purged log would restart the sequence at 1 - which the
 * server would read as a device replaying a log it should have discarded.
 */
const DEVICE = `
CREATE TABLE IF NOT EXISTS device (
  id                TEXT PRIMARY KEY CHECK (id = 'this'),
  device_id         TEXT NOT NULL,
  next_seq          INTEGER NOT NULL DEFAULT 1,
  server_cursor     INTEGER NOT NULL DEFAULT 0,
  blocked_on_seq    INTEGER,
  last_synced_at    TEXT,
  last_sync_error   TEXT
)`;

/** A damage assessment as it exists on the device, before and after it syncs. */
const ASSESSMENT = `
CREATE TABLE IF NOT EXISTS assessment (
  local_id                TEXT PRIMARY KEY,
  server_id               TEXT,
  public_ref              TEXT,
  household_id            TEXT NOT NULL,
  gn_division_id          TEXT NOT NULL,
  gn_division_code        TEXT NOT NULL,
  hazard_event_id         TEXT NOT NULL,
  category                TEXT NOT NULL,
  subcategory             TEXT NOT NULL DEFAULT '',
  cost_estimate_lkr_cents INTEGER NOT NULL,
  assessed_at             TEXT NOT NULL,
  latitude                REAL,
  longitude               REAL,
  gps_accuracy_m          INTEGER,
  status                  TEXT NOT NULL,
  updated_at              TEXT NOT NULL
)`;

/** A citizen report written on the device, whether or not it has reached incident-svc. */
const REPORT = `
CREATE TABLE IF NOT EXISTS report (
  local_id            TEXT PRIMARY KEY,
  server_id           TEXT,
  public_ref          TEXT,
  incident_type       TEXT,
  text                TEXT,
  language            TEXT NOT NULL,
  latitude            REAL,
  longitude           REAL,
  location_accuracy_m INTEGER,
  location_source     TEXT,
  people_at_risk      INTEGER,
  channel             TEXT NOT NULL DEFAULT 'APP',
  created_at          TEXT NOT NULL,
  status              TEXT NOT NULL
)`;

/**
 * The media queue, kept apart from the operation log on purpose.
 *
 * A 4MB photo on a 2G link must not hold up a 200-byte assessment record. Metadata syncs
 * first and photos follow, linked by `client_operation_id` - so an assessment is visible
 * to a reviewer within seconds of the device finding a signal, with its evidence arriving
 * behind it.
 */
const MEDIA_UPLOAD = `
CREATE TABLE IF NOT EXISTS media_upload (
  id                  TEXT PRIMARY KEY,
  client_operation_id TEXT NOT NULL,
  entity_type         TEXT NOT NULL,
  entity_local_id     TEXT NOT NULL,
  kind                TEXT NOT NULL CHECK (kind IN ('photo', 'audio')),
  local_uri           TEXT NOT NULL,
  content_type        TEXT NOT NULL,
  size_bytes          INTEGER NOT NULL,
  duration_seconds    REAL,
  sha256              TEXT,
  latitude            REAL,
  longitude           REAL,
  created_at          TEXT NOT NULL,
  status              TEXT NOT NULL CHECK (
    status IN ('pending', 'deferred', 'uploading', 'uploaded', 'failed', 'refused')
  ),
  attempt_count       INTEGER NOT NULL DEFAULT 0,
  bytes_sent          INTEGER NOT NULL DEFAULT 0,
  remote_key          TEXT,
  last_error          TEXT,
  uploaded_at         TEXT
)`;

/** Alerts pulled down for the citizen inbox, kept so the inbox works with no signal. */
const ALERT_CACHE = `
CREATE TABLE IF NOT EXISTS alert_cache (
  id             TEXT PRIMARY KEY,
  headline_si    TEXT NOT NULL,
  headline_ta    TEXT NOT NULL,
  headline_en    TEXT NOT NULL,
  body_si        TEXT NOT NULL,
  body_ta        TEXT NOT NULL,
  body_en        TEXT NOT NULL,
  severity       INTEGER NOT NULL,
  hazard_type    TEXT NOT NULL,
  area_codes     TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to   TEXT,
  received_at    TEXT NOT NULL,
  read_at        TEXT
)`;

/**
 * Shelters, cached for the home screen.
 *
 * On the emergency path, so it has to answer with no network: the moment somebody needs a
 * shelter is the moment the cell tower is congested. `cached_at` is kept per row and shown
 * on screen, because a shelter list from last night is a list that can send a household to
 * a building that is not open.
 */
const SHELTER_CACHE = `
CREATE TABLE IF NOT EXISTS shelter_cache (
  id               TEXT PRIMARY KEY,
  name_si          TEXT NOT NULL,
  name_ta          TEXT NOT NULL,
  name_en          TEXT NOT NULL,
  gn_division_code TEXT NOT NULL,
  latitude         REAL NOT NULL,
  longitude        REAL NOT NULL,
  capacity         INTEGER NOT NULL,
  occupancy        INTEGER NOT NULL,
  status           TEXT NOT NULL,
  cached_at        TEXT NOT NULL
)`;

const INDEXES: readonly string[] = [
  // The sync engine's hot query: the next batch, in seq order, for one status.
  'CREATE INDEX IF NOT EXISTS operation_log_status_seq ON operation_log (status, seq)',
  'CREATE INDEX IF NOT EXISTS operation_log_entity ON operation_log (entity_type, entity_local_id)',
  'CREATE INDEX IF NOT EXISTS media_upload_status ON media_upload (status, created_at)',
  'CREATE INDEX IF NOT EXISTS media_upload_operation ON media_upload (client_operation_id)',
  'CREATE INDEX IF NOT EXISTS assessment_status ON assessment (status, updated_at)',
  'CREATE INDEX IF NOT EXISTS alert_cache_effective ON alert_cache (effective_from DESC)',
];

/** Forward-only. The index into this array is `PRAGMA user_version`. */
export const MIGRATIONS: readonly (readonly string[])[] = [
  [OPERATION_LOG, DEVICE, ASSESSMENT, REPORT, MEDIA_UPLOAD, ALERT_CACHE, ...INDEXES],
  // 0002: the citizen surface. Shelters are cached because the home screen shows the
  // nearest one and has to do it with no network.
  [SHELTER_CACHE, 'CREATE INDEX IF NOT EXISTS shelter_cache_division ON shelter_cache (gn_division_code)'],
];

export const SCHEMA_VERSION = MIGRATIONS.length;

/**
 * Bring a database up to `SCHEMA_VERSION`.
 *
 * Returns the version it started at, which the caller logs - a device arriving several
 * versions behind is worth knowing about, because it has been offline that long.
 */
export async function migrate(db: Database): Promise<number> {
  for (const pragma of PRAGMAS) await db.execute(pragma);

  const [row] = await db.select<{ user_version: number }>('PRAGMA user_version');
  const from = row?.user_version ?? 0;

  for (let version = from; version < MIGRATIONS.length; version += 1) {
    const statements = MIGRATIONS[version];
    if (!statements) continue;
    await db.transaction(async (tx) => {
      for (const statement of statements) await tx.execute(statement);
    });
    // Outside the transaction: SQLite refuses to set user_version inside one on some
    // builds, and re-running an idempotent migration costs nothing.
    await db.execute(`PRAGMA user_version = ${version + 1}`);
  }

  return from;
}
