/**
 * A conflict, side by side, and the explicit choice it requires.
 *
 * The brief: "Conflicts shown side by side (local vs server) with an explicit user choice.
 * **Never auto-resolve.**"
 *
 * That rule is not a UI preference. A conflict on this platform means the server refused an
 * operation the officer believes they made — a household already assessed by someone else,
 * a sequence the server has already consumed, a category the schedule does not know. Every
 * one of those is a disagreement about what happened in a division, and the officer is the
 * only person who was there. Merging automatically would resolve it in favour of whoever
 * wrote the merge rule, silently, in a record that later becomes money.
 *
 * So: this module *describes* a conflict and *records* a decision. It contains no rule that
 * picks a side.
 *
 * A conflict also jams the queue behind it, by design (file 22). Everything after it waits,
 * because sequence ordering means skipping one would rebuild a household's record out of an
 * update whose create never arrived. That makes resolving a conflict urgent in a way that
 * the officer needs to be told about, which is why `blocking` is on the summary.
 */

import type { OperationRecord } from '../offline/log/types.js';
import { payloadOf } from '../offline/log/types.js';

/**
 * The reasons the server sends, from `ledger_svc.domain.sync`.
 *
 * Each maps to a sentence an officer can act on. An unrecognised reason falls back to the
 * server's own `detail` string rather than to "unknown error": the server said something
 * specific and dropping it helps nobody.
 */
export const CONFLICT_REASONS = [
  'seq_already_consumed',
  'unknown_category',
  'household_not_found',
  'assessment_already_exists',
] as const;

export type ConflictReason = (typeof CONFLICT_REASONS)[number];

export interface ConflictField {
  readonly field: string;
  /** What this device holds. Always shown, even when the two agree. */
  readonly local: string;
  /** What the server holds, or null where the server sent nothing for this field. */
  readonly server: string | null;
  readonly differs: boolean;
}

export type ConflictChoice = 'keep-local' | 'accept-server' | 'discard';

export interface ConflictSummary {
  readonly clientOperationId: string;
  readonly seq: number;
  readonly entityType: string;
  readonly reason: ConflictReason | 'unknown';
  /** One sentence, in the officer's terms, about what the server disagreed with. */
  readonly explanation: string;
  readonly fields: readonly ConflictField[];
  /** The choices this conflict actually offers. Never empty. */
  readonly choices: readonly ConflictChoice[];
  /** How many operations are waiting behind this one. */
  readonly blocking: number;
}

function explain(reason: string, detail: string | null): string {
  switch (reason) {
    case 'seq_already_consumed':
      return (
        'The server has already recorded a different change at this position in this ' +
        "device's sequence. That usually means this handset's queue was restored from an " +
        'export after some of it had already synced.'
      );
    case 'unknown_category':
      return (
        'The server does not recognise the damage category on this assessment. The copy of ' +
        'the cost schedule on this device may be newer or older than the one in use.'
      );
    case 'household_not_found':
      return (
        'The household this assessment names is not in the register the server holds. If ' +
        'you created it on this device, it has not reconciled yet.'
      );
    case 'assessment_already_exists':
      return (
        'An assessment for this household and this event already exists on the server, ' +
        'recorded by someone else or by this device before a reinstall.'
      );
    default:
      // The server said something this build does not have a sentence for. Its own words
      // beat a generic message: they are at least specific.
      return detail ?? 'The server refused this change and did not say why.';
  }
}

/**
 * Which choices a given conflict offers.
 *
 * Not the same set every time, and the differences matter. `accept-server` is only offered
 * where the server actually holds a competing record — offering it for
 * `household_not_found` would mean "accept nothing", which is `discard` with a misleading
 * label. `keep-local` is always offered because the officer was there.
 */
export function choicesFor(reason: string): readonly ConflictChoice[] {
  switch (reason) {
    case 'assessment_already_exists':
    case 'seq_already_consumed':
      return ['keep-local', 'accept-server', 'discard'];
    default:
      return ['keep-local', 'discard'];
  }
}

/**
 * Build the side-by-side view for one refused operation.
 *
 * Every field of the local payload is listed, including the ones that match, because an
 * officer deciding whether to keep their version needs to see the whole record rather than
 * a diff of the parts a rule thought were interesting.
 */
export function describeConflict(
  record: OperationRecord,
  { blocking = 0 }: { blocking?: number } = {},
): ConflictSummary {
  const detail = record.conflict_detail
    ? (JSON.parse(record.conflict_detail) as Record<string, unknown>)
    : {};
  const reason = typeof detail['reason'] === 'string' ? detail['reason'] : 'unknown';
  const serverPayload = (detail['server'] ?? {}) as Record<string, unknown>;

  let local: Record<string, unknown>;
  try {
    local = payloadOf(record);
  } catch {
    // A payload that will not parse cannot be shown side by side. The officer still has to
    // be told the operation is jamming the queue, so the conflict is described with no
    // fields rather than suppressed.
    local = {};
  }

  const fields: ConflictField[] = Object.entries(local).map(([field, value]) => {
    const serverValue = field in serverPayload ? serverPayload[field] : undefined;
    return {
      field,
      local: format(value),
      server: serverValue === undefined ? null : format(serverValue),
      differs: serverValue !== undefined && format(serverValue) !== format(value),
    };
  });

  return {
    clientOperationId: record.client_operation_id,
    seq: record.seq,
    entityType: record.entity_type,
    reason: (CONFLICT_REASONS as readonly string[]).includes(reason)
      ? (reason as ConflictReason)
      : 'unknown',
    explanation: explain(reason, record.last_error),
    fields,
    choices: choicesFor(reason),
    blocking,
  };
}

function format(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/**
 * Whether a screen may proceed on the officer's behalf.
 *
 * Always false. It exists as a named function rather than as an absence so that a future
 * change that wants to auto-resolve has to delete something and read this comment, rather
 * than quietly add a default branch to a switch.
 *
 * There is no rule that can pick correctly here. The officer was in the division; the
 * server was not.
 */
export function mayAutoResolve(): false {
  return false;
}
