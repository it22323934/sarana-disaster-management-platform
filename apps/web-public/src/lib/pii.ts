/**
 * The regex battery every public response is swept against.
 *
 * This is the file the whole app answers to. The privacy claim — no name, no NIC, no
 * phone, no household reference, no coordinate, anywhere a member of the public can read —
 * is enforced in three places that do not depend on each other: the SQL selects nothing
 * identifying, the response models carry no field for it, and this sweep reads the actual
 * bytes of every rendered route and every export and looks for it anyway.
 *
 * The third one exists because the first two are promises about intent. A page that
 * interpolated a district's `last_released_at` into a caption, or an export that added a
 * column "for debugging", would satisfy both and still publish something it should not.
 *
 * **Every pattern here is anchored in what this platform actually generates**, taken from
 * `gov_mock.data.names` and `tools/seed/generate.py`, not from a generic PII list. A
 * pattern that cannot match anything the system produces is a pattern that makes the sweep
 * look thorough while catching nothing.
 */

export interface PiiPattern {
  /** What it finds, in the words of a reviewer reading a failure. */
  readonly name: string;
  readonly pattern: RegExp;
  /** Why publishing a match would be harmful. Printed on failure. */
  readonly why: string;
}

/**
 * Sri Lanka's bounding box, used to decide whether a decimal pair is a coordinate here.
 *
 * The country spans roughly 5.9-9.9 N and 79.6-81.9 E. A looser test would flag every
 * percentage and currency figure on the site; a tighter one would miss a leak by a
 * hundredth of a degree, which is still a house.
 */
export const LK_BBOX = { minLat: 5.9, maxLat: 9.9, minLon: 79.6, maxLon: 81.9 } as const;

export const PII_PATTERNS: readonly PiiPattern[] = [
  {
    name: 'NIC (new format, 12 digits)',
    // Twelve digits in a row, bounded by non-hex characters.
    //
    // The boundary is `[0-9a-fA-F]` rather than `\d`, and that is load-bearing. Every
    // ledger entry on this site carries a 64-character SHA-256 digest and two UUIDs, and a
    // run of twelve digits inside a hex string happens often enough to fire on most pages.
    // A sweep that cries wolf on `/ledger` is a sweep somebody switches off, which is a
    // worse outcome than the false positives it was catching.
    pattern: /(?<![0-9a-fA-F])\d{12}(?![0-9a-fA-F])/g,
    why: 'A National Identity Card number identifies one person completely and permanently.',
  },
  {
    name: 'NIC (old format, 9 digits and V or X)',
    pattern: /(?<![0-9a-zA-Z])\d{9}[VXvx](?![0-9a-zA-Z])/g,
    why: 'The pre-2016 card format. Anyone holding an old card still holds it.',
  },
  {
    name: 'Sri Lankan mobile number',
    // Both the shapes this platform produces: +94 7X ... from `generate_msisdn`, and the
    // local 07X ... form a person would type into a grievance form.
    pattern: /(?<![\w+])(?:\+94|0)7[0-8]\d{7}(?![\d])/g,
    why: 'A phone number reaches a specific handset. This platform sends evacuation orders.',
  },
  {
    name: 'Household reference code',
    // `HH-LK-21-010301` from `tools/seed/generate.py`. It is the join key to a household
    // row, so publishing one turns every aggregate on the page into a lookup.
    pattern: /\bHH-LK-\d{2}-\d{6}\b/g,
    why: 'The household reference resolves to one family in the registry.',
  },
  {
    name: 'GN division code',
    // `LK-21-03-014`. Not personal data on its own, and it is on the wrong side of the
    // privacy floor: money is published no finer than DS division, and a GN code beside a
    // figure is how a small-cell suppression gets undone by a caption.
    pattern: /\bLK-\d{2}-\d{2}-\d{3}\b/g,
    why: 'Money is published no finer than DS division. A GN code beside a figure undoes the suppression.',
  },
  {
    name: 'Sri Lankan coordinate pair',
    // A decimal degree pair inside the national bounding box, in either order, however it
    // is punctuated. The bbox check happens in `findPii` because a regex cannot compare
    // magnitudes.
    pattern: /(-?\d{1,3}\.\d{3,})\s*[,;]\s*(-?\d{1,3}\.\d{3,})/g,
    why: 'A coordinate is a house. The brief forbids one at any zoom level.',
  },
  {
    name: 'EWKT or WKT geometry',
    pattern: /\b(?:SRID=\d+;)?(?:MULTI)?(?:POINT|POLYGON|LINESTRING)\s*\(/gi,
    why: 'Raw geometry in a response body is a boundary or a position that was never meant to leave the database.',
  },
  {
    name: 'Email address',
    /**
     * The domain must end in a letter TLD, and that is not pedantry.
     *
     * `[\w.+-]+@[\w-]+\.[\w.-]+` also matches a pnpm dependency path — `next@15.5.24_`,
     * `@babel+core@7.29.7_` — which appear by the dozen in a development RSC payload. The
     * first run of this sweep reported forty findings per page, none of them an email,
     * which is precisely how a real one would have been missed in the noise.
     */
    pattern: /\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-zA-Z]{2,}\b/g,
    why: 'An officer or citizen email address identifies a person and invites targeting.',
  },
] as const;

export interface PiiFinding {
  readonly pattern: string;
  readonly why: string;
  readonly match: string;
  /** Characters either side of the match, so a failure says where to look. */
  readonly context: string;
}

/**
 * Text that is allowed to look like a match.
 *
 * Kept short and specific on purpose. Every entry here is a hole in the sweep, so each one
 * names exactly what it excuses and nothing broader.
 */
const ALLOWED: readonly RegExp[] = [
  // The documentation on /verify shows a worked NIC-shaped example and a coordinate pair
  // so a reader can see what the platform refuses to publish. They are inside an element
  // marked `data-sarana-pii-example`, which `stripExamples` removes before the sweep -
  // this entry is the belt to that braces, matching the literal placeholders themselves.
  /\b1{9}[VX]\b/,
  /\b9{12}\b/,
  /**
   * The coordinate placeholder on `/verify`.
   *
   * Repeating digits, so it reads as a placeholder rather than as a location, and inside
   * the national bounding box, so it demonstrates the shape the sweep actually detects.
   *
   * It is allowed by literal rather than by the `data-sarana-pii-example` marker, because
   * the sweep reads the RSC flight payload as well as the rendered text — and there the
   * marker is a serialised prop (`\"data-sarana-pii-example\":true`) rather than an HTML
   * attribute `stripExamples` can match. The marker still covers the visible-text pass.
   */
  /^7\.11111,\s*80\.22222$/,
];

/**
 * Whole tokens that are published, structured identifiers of *things* rather than of people.
 *
 * **This list exists because the sweep failed on correct pages.** A NIC is twelve digits,
 * and so is the tail of every UUID (`…-000000000009`) and of every mock payment reference
 * (`MOCK-BANK_TRANSFER-000000000001`). Both appear on `/ledger` and in the JSON export by
 * design — the payment reference is the field an auditor reconciles against a bank
 * statement — so without this the sweep fired on every ledger page. The fix somebody
 * reaches for at that point is to loosen the NIC pattern until it catches nothing, which is
 * how a privacy gate quietly stops being one.
 *
 * The test is **containment**: a candidate escapes only when it falls inside one of these
 * shapes. A NIC in a sentence is inside none of them and is still caught. See
 * `publishedSpans` for why containment rather than tokenisation.
 *
 * Nothing here identifies a person. A UUID has no public resolver, a payment reference
 * names a transfer, a digest names a record. The household reference — which *does* resolve
 * to a family — is deliberately absent, so `HH-LK-21-010301` remains a finding.
 */
const PUBLISHED_TOKENS: readonly RegExp[] = [
  // UUID, any version: `entitlement_id` and `released_by` in the public feed, and every
  // React key and element id built from one.
  /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/,
  // `MOCK-BANK_TRANSFER-0000000004D2`. Every reference in Phase 1 begins `MOCK-`, and the
  // prefix is required rather than optional: a bare twelve-hex run is not excused.
  /MOCK-[A-Z_]+-[0-9A-Fa-f]{12}/,
  // A SHA-256 digest: an entry hash, a previous hash, a Merkle root.
  /[0-9a-fA-F]{64}/,
];

/**
 * Where in the text a published identifier sits.
 *
 * **Containment, not tokenisation, and the difference is what the first run taught.** The
 * obvious implementation takes the whitespace-delimited token around a match and asks
 * whether the whole token is a published identifier. That works on a plain page and fails
 * on the two places these identifiers actually appear:
 *
 *   - As a DOM id or React key with a prefix — `schedule-018f3c2a-…-000000000001`, whose
 *     token is not a bare UUID.
 *   - Inside the RSC flight payload, where every value is JSON-escaped and the token picks
 *     up the surrounding `\"` — `\MOCK-BANK_TRANSFER-000000000001\`.
 *
 * Both are correct output. Asking instead whether the match *falls inside* a published
 * identifier is indifferent to what surrounds it, which is the property that matters: the
 * twelve digits are the tail of a UUID regardless of what was concatenated onto the front.
 */
function publishedSpans(text: string): ReadonlyArray<readonly [number, number]> {
  const spans: Array<readonly [number, number]> = [];

  for (const pattern of PUBLISHED_TOKENS) {
    const scan = new RegExp(pattern.source, 'g');
    let match: RegExpExecArray | null;
    while ((match = scan.exec(text)) !== null) {
      spans.push([match.index, match.index + match[0].length]);
    }
  }

  return spans;
}

/**
 * Remove the parts of a page that deliberately show a PII *shape*.
 *
 * `/verify` and `/methodology` explain what is withheld, and explaining it well means
 * showing the reader the shape of the thing. Those examples are wrapped in
 * `data-sarana-pii-example`, which is a documented, greppable marker rather than an
 * exclusion list of URLs - so a page that starts printing real values cannot be excused by
 * having been added to a list once.
 */
export function stripExamples(html: string): string {
  return html.replace(/<[^>]*data-sarana-pii-example[^>]*>[\s\S]*?<\/[a-zA-Z]+>/g, ' ');
}

function looksLikeSriLankanCoordinate(first: string, second: string): boolean {
  const a = Number.parseFloat(first);
  const b = Number.parseFloat(second);
  const inBox = (lat: number, lon: number) =>
    lat >= LK_BBOX.minLat && lat <= LK_BBOX.maxLat && lon >= LK_BBOX.minLon && lon <= LK_BBOX.maxLon;
  // Either order: GeoJSON writes lon,lat and almost everything a human types is lat,lon.
  return inBox(a, b) || inBox(b, a);
}

/** Every PII-shaped thing in a body of text, with enough context to find it. */
export function findPii(text: string): readonly PiiFinding[] {
  const findings: PiiFinding[] = [];
  // Computed once for the whole body rather than per match: a ledger page carries a few
  // hundred identifiers and rescanning for each candidate would be quadratic.
  const published = publishedSpans(text);

  for (const { name, pattern, why } of PII_PATTERNS) {
    // A fresh RegExp per call: the module-level ones carry /g, and a shared lastIndex
    // makes the second sweep of the same pattern start halfway through the page and miss
    // matches non-deterministically.
    const scan = new RegExp(pattern.source, pattern.flags);
    let match: RegExpExecArray | null;

    while ((match = scan.exec(text)) !== null) {
      const found = match[0];
      if (ALLOWED.some((allowed) => allowed.test(found))) continue;

      // A match inside a published identifier is not a finding. See `publishedSpans`.
      const start = match.index;
      const end = start + found.length;
      if (published.some(([from, to]) => start >= from && end <= to)) continue;

      if (
        name === 'Sri Lankan coordinate pair' &&
        !looksLikeSriLankanCoordinate(match[1] ?? '', match[2] ?? '')
      ) {
        continue;
      }

      findings.push({
        pattern: name,
        why,
        match: found,
        context: text.slice(Math.max(0, match.index - 60), match.index + found.length + 60),
      });
    }
  }

  return findings;
}

/** A failure message a reviewer can act on without opening the page. */
export function describeFindings(where: string, findings: readonly PiiFinding[]): string {
  return [
    `${findings.length} PII-shaped value(s) in ${where}:`,
    ...findings.map(
      (finding) =>
        `  [${finding.pattern}] ${finding.match}\n` +
        `    why it matters: ${finding.why}\n` +
        `    context: ...${finding.context.replace(/\s+/g, ' ').trim()}...`,
    ),
  ].join('\n');
}

/**
 * Sweep a parsed JSON payload, testing strings and keys but never numbers.
 *
 * The exports are swept differently from the pages, and the reason is a property of the
 * data rather than a convenience. Every identifier this platform can leak is typed as a
 * string: a NIC, a phone number, a household reference and a hash are all `str` in the
 * Pydantic models and all quoted in the JSON. Every *number* in a public payload is an
 * amount in cents, a count, or a sequence.
 *
 * Running the digit patterns over numbers would therefore catch nothing real and would
 * fire on the true ones: a national total of Rs. 4.18bn is `418234000000` in cents, which
 * is twelve digits and indistinguishable from a NIC to a regex. The sweep would fail on
 * the most important figure on the site being correct, and the fix somebody reached for
 * would be to loosen the NIC pattern.
 *
 * Keys are swept too. A response that grew a `household_ref` key leaks the fact that the
 * field exists even before anyone looks at its value.
 */
export function findPiiInJson(value: unknown, path = '$'): readonly PiiFinding[] {
  const findings: PiiFinding[] = [];

  const walk = (node: unknown, where: string): void => {
    if (typeof node === 'string') {
      for (const finding of findPii(node)) {
        findings.push({ ...finding, context: `${where}: ${finding.context}` });
      }
      return;
    }
    if (Array.isArray(node)) {
      node.forEach((item, index) => walk(item, `${where}[${index}]`));
      return;
    }
    if (node !== null && typeof node === 'object') {
      for (const [key, child] of Object.entries(node)) {
        for (const finding of findPii(key)) {
          findings.push({ ...finding, context: `${where} key: ${key}` });
        }
        walk(child, `${where}.${key}`);
      }
    }
  };

  walk(value, path);
  return findings;
}

/**
 * The visible text of a rendered page, with the markup and the scripts taken out.
 *
 * Script and style contents are dropped before tags: a `<script>` body is not text a
 * reader sees, and Next's RSC flight payload lives in one. Sweeping it would double every
 * finding and report the same leak twice with different context, which makes a real
 * failure harder to read rather than easier.
 *
 * The RSC payload is swept separately by the JSON sweep in the same test, so nothing is
 * lost by excluding it here.
 */
export function visibleText(html: string): string {
  return stripExamples(html)
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ');
}
