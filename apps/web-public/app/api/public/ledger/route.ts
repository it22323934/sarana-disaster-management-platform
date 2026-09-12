/**
 * `/api/public/ledger` — the stable feed the brief asks for, and the CSV export.
 *
 * **This is a thin, honest proxy and not a second source of truth.** It forwards to
 * ledger-svc's `/api/v1/ledger/public`, passes the fields through unchanged, and adds
 * `upstream` so a consumer can go straight to the origin and stop depending on this app.
 * The alternative — recomputing or reshaping the entries here — would create a second
 * definition of a published entry, and `tools/sarana-verify` recomputes hashes over the
 * origin's shape. Two shapes means one of them eventually fails verification for a reason
 * that has nothing to do with tampering.
 *
 * It exists at all because the brief asks for "a stable JSON feed at `/api/public/ledger`
 * for programmatic access": a URL on the site a reader is already looking at, that does not
 * require them to know the service topology. The origin URL is in the payload so that
 * knowing it is one request away.
 *
 * `format=csv` is the same rows as a spreadsheet. It is generated here rather than added to
 * the Python service because CSV is a presentation concern of this page — the columns are
 * the ones the table shows, in the order it shows them.
 *
 * Not statically cached: `force-dynamic`, because the feed is paged by a query parameter
 * and a cached first page served for every `from_seq` would silently hand a verifier the
 * wrong entries. `Cache-Control` still lets the ALB hold it briefly (ADR-010).
 */

import { NextResponse, type NextRequest } from 'next/server';

import { getLedgerPage } from '../../../../src/lib/public-api';
import { publicUrl } from '../../../../src/lib/services';

export const dynamic = 'force-dynamic';

/** Matches the API's own ceiling. A larger request is clamped rather than refused. */
const MAX_LIMIT = 5000;
const DEFAULT_LIMIT = 1000;

/**
 * The CSV columns, in order.
 *
 * Every one of them is already in the JSON feed. Nothing is added, and in particular no
 * "helpful" derived column: a CSV that carried a district or a division would put money
 * below the privacy floor into a spreadsheet, which is exactly the shape that gets
 * pivoted.
 */
const CSV_COLUMNS = [
  'seq',
  'released_at',
  'amount_lkr_cents',
  'payment_rail',
  'payment_ref',
  'entry_hash',
  'prev_hash',
  'anchor_date',
  'reversed',
] as const;

/**
 * Escape one CSV field.
 *
 * The leading-character guard is not decoration. A field beginning `=`, `+`, `-` or `@` is
 * interpreted as a formula by Excel and Sheets, which is a live code-execution path out of
 * a downloaded file. Nothing in this feed should ever begin with one — the fields are
 * numbers, ISO timestamps and hex — but the export is the artefact that leaves our control
 * entirely, so it is not the place to rely on that staying true.
 */
function csvField(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value);
  const guarded = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
  return /[",\n\r]/.test(guarded) ? `"${guarded.replace(/"/g, '""')}"` : guarded;
}

export async function GET(request: NextRequest): Promise<NextResponse | Response> {
  const params = request.nextUrl.searchParams;

  const fromSeq = Math.max(0, Number.parseInt(params.get('from_seq') ?? '0', 10) || 0);
  const limit = Math.min(
    MAX_LIMIT,
    Math.max(1, Number.parseInt(params.get('limit') ?? String(DEFAULT_LIMIT), 10) || DEFAULT_LIMIT),
  );

  const page = await getLedgerPage(fromSeq, limit);

  if (!page.ok) {
    // 502, not 500: this app is working and the thing behind it is not. The distinction
    // matters to whoever is paged, and to a script deciding whether to retry.
    return NextResponse.json(
      {
        error: 'upstream_unavailable',
        reason: page.reason,
        detail:
          'The ledger service did not answer. This endpoint is a proxy and holds no copy ' +
          'of the feed; read the upstream URL directly to confirm.',
        upstream: publicUrl('ledger-svc', 'ledger/public'),
      },
      { status: 502, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  if (params.get('format') === 'csv') {
    const rows = [
      CSV_COLUMNS.join(','),
      ...page.data.entries.map((entry) =>
        CSV_COLUMNS.map((column) => csvField(entry[column])).join(','),
      ),
    ];

    return new Response(`${rows.join('\r\n')}\r\n`, {
      headers: {
        // charset is explicit: a BOM-less UTF-8 CSV opened in a Windows Excel defaults to
        // the ANSI codepage, and while nothing in these columns is non-ASCII today, the
        // header costs nothing and stops that being a future surprise.
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': `attachment; filename="sarana-ledger-${fromSeq}.csv"`,
        'Cache-Control': 'public, max-age=60',
      },
    });
  }

  return NextResponse.json(
    {
      ...page.data,
      // Where this came from, so a consumer can cut this app out of the loop entirely.
      // A transparency feed that only exists behind one website is a feed whose
      // availability is a single organisation's decision.
      upstream: publicUrl('ledger-svc', 'ledger/public'),
    },
    {
      headers: {
        'Cache-Control': 'public, max-age=60',
        // The feed is meant to be read by other people's scripts from other origins.
        // There is no credential to protect and no cookie in play, so a wildcard is the
        // correct policy rather than a lax one.
        'Access-Control-Allow-Origin': '*',
      },
    },
  );
}
