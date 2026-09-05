/**
 * The ledger, as CSV.
 *
 * The brief asks for the ledger browser to be "exportable to CSV", and the reason is not
 * convenience: an auditor who can only read the ledger through this console can only audit
 * what this console chooses to show them. A file they can open in their own tools, against
 * their own copy, is the difference between reviewing the ledger and reviewing our
 * rendering of it.
 *
 * **The hashes are in the export, in full.** Truncating them for width would produce a
 * file from which the chain cannot be re-verified, which is the one thing the export is
 * for. `prev_hash` and `entry_hash` are the whole point of a row.
 *
 * **Every field is quoted and every embedded quote doubled.** RFC 4180. A summary field
 * containing a comma silently shifts every column after it, and a shifted column in a
 * financial ledger reads as a different amount against a different entry.
 *
 * **The header row names the hashing scheme's fields exactly as the API does.** An auditor
 * matching this file against `GET /ledger` should not have to guess which column is which.
 *
 * Deliberately a pure function returning a string, with no DOM in it, so the CSV can be
 * asserted in a unit test rather than only in a browser.
 */

import type { LedgerEntry } from '../lib/schemas';

/** RFC 4180: wrap in quotes, double any quote inside. */
export function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

export const LEDGER_COLUMNS = [
  'seq',
  'id',
  'entry_type',
  'amount_lkr_cents',
  'prev_hash',
  'entry_hash',
  'anchor_date',
  'created_at',
] as const;

/**
 * The ledger rows as an RFC 4180 CSV.
 *
 * Amounts stay in **cents, as integers**, exactly as the API returns them. Converting to
 * rupees here would introduce a decimal representation into a file whose purpose is
 * arithmetic that must be exact, and a spreadsheet reading `12500.00` as a float is how a
 * reconciliation ends up off by a cent per row.
 */
export function ledgerToCsv(entries: readonly LedgerEntry[]): string {
  const header = LEDGER_COLUMNS.map(csvCell).join(',');
  const rows = entries.map((entry) =>
    LEDGER_COLUMNS.map((column) => csvCell(entry[column as keyof LedgerEntry])).join(','),
  );
  // CRLF, which is what RFC 4180 specifies and what Excel expects on the platform this is
  // most likely to be opened on.
  return [header, ...rows].join('\r\n') + '\r\n';
}

/**
 * A filename that says what is inside it.
 *
 * The seq range is in the name, because an auditor with three exports in a downloads
 * folder needs to tell them apart without opening each one - and because a file called
 * `ledger.csv` invites the belief that it is the whole ledger.
 */
export function ledgerFilename(entries: readonly LedgerEntry[]): string {
  if (entries.length === 0) return 'sarana-ledger-empty.csv';
  const seqs = entries.map((entry) => entry.seq);
  return `sarana-ledger-${Math.min(...seqs)}-${Math.max(...seqs)}.csv`;
}
