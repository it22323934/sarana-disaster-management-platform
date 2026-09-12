/**
 * The CSV export, and the ways a ledger export can quietly lie.
 *
 * An auditor who can only read the ledger through this console can only audit what this
 * console chooses to show them. The export is what lets them check it in their own tools,
 * so the failures that matter are the ones that produce a plausible file rather than a
 * broken one.
 */

import { describe, expect, it } from 'vitest';

import { LEDGER_COLUMNS, csvCell, ledgerFilename, ledgerToCsv } from './ledger-export';
import type { LedgerEntry } from '../lib/schemas';

function entry(overrides: Partial<LedgerEntry> = {}): LedgerEntry {
  return {
    seq: 4117,
    id: '018f3c2a-0001-7e90-9c2d-000000000001',
    entry_type: 'DISBURSEMENT',
    amount_lkr_cents: 12_500_000,
    prev_hash: 'a'.repeat(64),
    entry_hash: 'b'.repeat(64),
    anchor_date: '2025-11-28',
    created_at: '2025-11-28T04:30:00Z',
    ...overrides,
  };
}

describe('a cell', () => {
  it('doubles an embedded quote rather than escaping it with a backslash', () => {
    // RFC 4180. A backslash escape is a C convention and no spreadsheet reads it.
    expect(csvCell('she said "flooded"')).toBe('"she said ""flooded"""');
  });

  it('quotes a value containing a comma', () => {
    // The failure this prevents is silent: an unquoted comma shifts every column after it,
    // and a shifted column in a financial ledger reads as a different amount against a
    // different entry.
    const row = ledgerToCsv([entry({ entry_type: 'ADJUSTMENT, MANUAL' })]);
    expect(row).toContain('"ADJUSTMENT, MANUAL"');
    expect(row.split('\r\n')[1]?.split('","').length).toBe(LEDGER_COLUMNS.length);
  });

  it('renders null as empty rather than as the word null', () => {
    expect(csvCell(null)).toBe('""');
    expect(csvCell(undefined)).toBe('""');
  });
});

describe('the export', () => {
  it('carries both hashes in full', () => {
    // Truncating for width would produce a file from which the chain cannot be
    // re-verified, which is the one thing this export is for.
    const csv = ledgerToCsv([entry()]);
    expect(csv).toContain('a'.repeat(64));
    expect(csv).toContain('b'.repeat(64));
  });

  it('keeps amounts in integer cents', () => {
    // Not rupees. This file exists for arithmetic that must be exact, and a spreadsheet
    // reading 125000.00 as a float is how a reconciliation ends up off by a cent per row.
    expect(ledgerToCsv([entry()])).toContain('"12500000"');
    expect(ledgerToCsv([entry()])).not.toContain('125000.00');
  });

  it('names every column in the header, in the order the rows are written', () => {
    const [header, row] = ledgerToCsv([entry()]).split('\r\n');
    expect(header).toBe(LEDGER_COLUMNS.map((column) => `"${column}"`).join(','));
    expect(row?.split(',').length).toBe(LEDGER_COLUMNS.length);
  });

  it('uses CRLF, which is what RFC 4180 specifies', () => {
    expect(ledgerToCsv([entry()])).toMatch(/\r\n$/);
  });

  it('writes a header and nothing else for an empty page', () => {
    // A zero-row file is a real answer to a filtered query. An empty string would look
    // like a failed download.
    const lines = ledgerToCsv([]).split('\r\n').filter((line) => line.length > 0);
    expect(lines).toHaveLength(1);
  });
});

describe('the filename', () => {
  it('carries the sequence range', () => {
    // An auditor with three exports in a downloads folder needs to tell them apart without
    // opening each one - and a file called `ledger.csv` invites the belief that it is the
    // whole ledger.
    expect(ledgerFilename([entry({ seq: 10 }), entry({ seq: 4117 })])).toBe(
      'sarana-ledger-10-4117.csv',
    );
  });

  it('says so when there is nothing in it', () => {
    expect(ledgerFilename([])).toBe('sarana-ledger-empty.csv');
  });
});
