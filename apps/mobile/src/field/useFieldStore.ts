/**
 * What every Field Companion screen needs, assembled once.
 *
 * The register and the schedule are built from the offline database the `OfflineProvider`
 * already owns, so the screens do not each open their own handle. It is a hook rather than
 * a provider because there is nothing to broadcast: every value here is derived from
 * things that are already in context, and adding a fourth provider layer would put the
 * register above the database that backs it.
 *
 * **The cipher is resolved here and nowhere else.** Screens never see a key, and the one
 * place the keystore is read is the one place to look when the encryption story is
 * reviewed.
 */

import { useMemo } from 'react';

import { HouseholdRegister, type RegistryCipher } from './household-register.js';
import { DEFAULT_HOUSEHOLD_CAP_CENTS, type CostSchedule, type ScheduleLine } from './entitlement.js';
import type { Database } from '../offline/db/types.js';

/**
 * The cipher the register uses on a handset.
 *
 * A placeholder that **refuses rather than storing plaintext**, and that choice is the
 * whole point. `expo-secure-store` plus AES-GCM is the real implementation and it is not
 * wired yet; an implementation that returned the plaintext unchanged would let the register
 * work perfectly in a demo while writing every household's name to disk in the clear.
 *
 * A screen that hits this gets a named failure it can show. That is a visibly broken
 * register, which is recoverable; the alternative is an invisibly leaking one.
 */
export const unavailableCipher: RegistryCipher = {
  async encrypt() {
    throw new Error(
      'the household register needs a device key and none is configured. Names are never ' +
        'written to this device unencrypted, so the register stays empty until the key ' +
        'exists.',
    );
  },
  async decrypt() {
    throw new Error('the household register needs a device key and none is configured.');
  },
  async searchHash() {
    throw new Error('the household register needs a device key and none is configured.');
  },
};

export interface ScheduleRow {
  readonly line_id: string;
  readonly version: string;
  readonly category: string;
  readonly unit_amount_cents: number;
  readonly max_units: number;
  readonly formula: string;
  readonly household_cap_cents: number;
  readonly description_si: string;
  readonly description_ta: string;
  readonly description_en: string;
  readonly cached_at: string;
}

/**
 * Read the cached schedule out of the device database.
 *
 * Returns null when there is none, and the form shows that rather than defaulting: an
 * officer pricing damage against an invented schedule would produce figures nobody can
 * reproduce, and would not know.
 */
export async function loadCachedSchedule(db: Database): Promise<CostSchedule | null> {
  const rows = await db.select<ScheduleRow>(
    'SELECT * FROM schedule_line ORDER BY version DESC, category',
  );
  if (rows.length === 0) return null;

  // The newest version present. A device that pulled a new schedule while an older one was
  // still cached prices against the newer, which is what the office will recompute with.
  const version = rows[0]!.version;
  const lines: Record<string, ScheduleLine> = {};
  for (const row of rows.filter((candidate) => candidate.version === version)) {
    lines[row.category] = {
      line_id: row.line_id,
      category: row.category,
      unit_amount_cents: row.unit_amount_cents,
      max_units: row.max_units,
      formula: row.formula,
    };
  }

  return {
    version,
    lines,
    household_cap_cents: rows[0]!.household_cap_cents || DEFAULT_HOUSEHOLD_CAP_CENTS,
    cached_at: rows[0]!.cached_at,
  };
}

/** The trilingual label for a category, from the cached schedule. */
export async function categoryLabels(
  db: Database,
  locale: 'si' | 'ta' | 'en',
): Promise<Record<string, string>> {
  const rows = await db.select<ScheduleRow>('SELECT * FROM schedule_line');
  const column = `description_${locale}` as keyof ScheduleRow;
  return Object.fromEntries(
    rows.map((row) => [row.category, (row[column] as string) || row.category]),
  );
}

/** The register, bound to the device database. Null until the database is open. */
export function useHouseholdRegister(
  db: Database | null,
  cipher: RegistryCipher = unavailableCipher,
): HouseholdRegister | null {
  return useMemo(() => (db ? new HouseholdRegister(db, cipher) : null), [db, cipher]);
}

export interface FieldContext {
  readonly gn_division_id: string;
  readonly gn_division_code: string;
  readonly hazard_event_id: string | null;
  readonly hazard_event_name: string | null;
  readonly register_synced_at: string | null;
}

/**
 * The division and hazard event this device is working inside.
 *
 * Null when the device has never been given one, which is a real state on a freshly issued
 * handset. The assessment form refuses in that case rather than inventing a hazard event
 * id: the server would refuse it on sync, three days later, in a division the officer has
 * already left.
 */
export async function loadFieldContext(db: Database): Promise<FieldContext | null> {
  const [row] = await db.select<FieldContext>(
    "SELECT gn_division_id, gn_division_code, hazard_event_id, hazard_event_name, " +
      "register_synced_at FROM field_context WHERE id = 'this'",
  );
  return row ?? null;
}

/** Record the division and event this device has been activated for. */
export async function setFieldContext(
  db: Database,
  context: {
    readonly gnDivisionId: string;
    readonly gnDivisionCode: string;
    readonly hazardEventId?: string | null;
    readonly hazardEventName?: string | null;
    readonly registerSyncedAt?: string | null;
  },
  { now = Date.now() }: { now?: number } = {},
): Promise<void> {
  await db.execute(
    "INSERT OR REPLACE INTO field_context (id, gn_division_id, gn_division_code, " +
      'hazard_event_id, hazard_event_name, register_synced_at, updated_at) ' +
      "VALUES ('this', ?, ?, ?, ?, ?, ?)",
    [
      context.gnDivisionId,
      context.gnDivisionCode,
      context.hazardEventId ?? null,
      context.hazardEventName ?? null,
      context.registerSyncedAt ?? null,
      new Date(now).toISOString(),
    ],
  );
}
