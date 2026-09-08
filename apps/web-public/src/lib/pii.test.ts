/**
 * The PII battery catches what it claims to, and does not cry wolf.
 *
 * The sweep in `e2e/pii-sweep.spec.ts` asserts that no page matches these patterns. That
 * test passes trivially if the patterns match nothing, so this file is the other half: it
 * feeds the battery values this platform really produces and asserts each one is caught.
 *
 * Every positive case below is taken from a generator in this repository —
 * `gov_mock.data.names.generate_nic`, `generate_msisdn`, `tools/seed/generate.py` — rather
 * than invented. A pattern tested against a value the system cannot produce is a pattern
 * that proves nothing.
 *
 * The negative cases matter as much. A sweep that fired on a 64-character hash or a
 * twelve-digit cents amount would fail on `/ledger` and on the headline figure being
 * correct, and the fix somebody reached for would be to loosen the NIC pattern.
 */

import { describe, expect, it } from 'vitest';

import { findPii, findPiiInJson, stripExamples, visibleText } from './pii';

const names = (text: string) => findPii(text).map((finding) => finding.pattern);

describe('the battery catches what this platform can produce', () => {
  it('finds a new-format NIC', () => {
    expect(names('Head of household 199712345670 requested review')).toContain(
      'NIC (new format, 12 digits)',
    );
  });

  it('finds an old-format NIC, in either case', () => {
    expect(names('NIC 771234567V')).toContain('NIC (old format, 9 digits and V or X)');
    expect(names('NIC 771234567x')).toContain('NIC (old format, 9 digits and V or X)');
  });

  it('finds a mobile number in both the shapes the platform writes', () => {
    // `generate_msisdn` produces the +94 form; a citizen typing into a grievance form
    // produces the other.
    expect(names('contact +94771234567')).toContain('Sri Lankan mobile number');
    expect(names('contact 0771234567')).toContain('Sri Lankan mobile number');
  });

  it('finds a household reference code', () => {
    expect(names('HH-LK-21-010301 received')).toContain('Household reference code');
  });

  it('finds a GN division code, which is below the privacy floor', () => {
    expect(names('Disbursed in LK-21-03-014')).toContain('GN division code');
  });

  it('finds a coordinate pair inside Sri Lanka, in either axis order', () => {
    expect(names('at 7.29070, 80.63370')).toContain('Sri Lankan coordinate pair');
    expect(names('at 80.63370, 7.29070')).toContain('Sri Lankan coordinate pair');
  });

  it('finds raw geometry', () => {
    expect(names('SRID=4326;MULTIPOLYGON(((79.81 6.89')).toContain('EWKT or WKT geometry');
  });

  it('finds an email address', () => {
    expect(names('officer.name@gov.lk')).toContain('Email address');
  });
});

describe('the battery does not fire on the figures this site exists to publish', () => {
  it('ignores a twelve-digit cents amount inside a hash', () => {
    // A 64-character digest with a run of twelve digits in it. Without the hex boundary
    // this is a NIC match on most ledger pages.
    const digest = 'ab123456789012cd' + 'f'.repeat(48);
    expect(names(digest)).toEqual([]);
  });

  it('ignores a UUID', () => {
    expect(names('018f3c2a-0009-7e90-9c2d-000000000009')).toEqual([]);
  });

  it('ignores a formatted national total', () => {
    // `LKR 4,182,340,000` — the headline figure. The digits are grouped, so no twelve-digit
    // run exists in the rendered page at all.
    expect(names('LKR 4,182,340,000')).toEqual([]);
  });

  it('ignores a district and a DS division code', () => {
    expect(names('LK-21 and LK-21-03')).toEqual([]);
  });

  it('ignores a mock payment reference', () => {
    expect(names('MOCK-BANK_TRANSFER-000000000001')).toEqual([]);
  });

  it('ignores a coordinate pair outside Sri Lanka', () => {
    // A percentage pair, or a figure from somewhere else. The bounding-box check is what
    // stops the coordinate pattern flagging ordinary decimals on every page.
    expect(names('51.50720, -0.12760')).toEqual([]);
  });

  it('ignores an ISO timestamp', () => {
    expect(names('2026-09-07T18:30:00+00:00')).toEqual([]);
  });
});

describe('the JSON sweep tests strings and keys but never numbers', () => {
  it('flags an identifier that arrives as a string value', () => {
    const findings = findPiiInJson({ entries: [{ note: 'paid to 199712345670' }] });
    expect(findings.map((f) => f.pattern)).toContain('NIC (new format, 12 digits)');
  });

  it('flags a key that names a field that should not exist', () => {
    const findings = findPiiInJson({ 'HH-LK-21-010301': 1 });
    expect(findings.map((f) => f.pattern)).toContain('Household reference code');
  });

  it('does not flag a twelve-digit money figure, which is a number', () => {
    // The national total in cents. As a JSON number it cannot be an identifier, because
    // every identifier in these payloads is typed as a string.
    expect(findPiiInJson({ assessed_lkr_cents: 418234000000 })).toEqual([]);
  });

  it('names the path so a failure can be found', () => {
    const findings = findPiiInJson({ districts: [{ label: '0771234567' }] });
    expect(findings[0]?.context).toContain('$.districts[0].label');
  });
});

describe('documented examples are excluded, and only where they are marked', () => {
  it('strips an element marked as a PII example', () => {
    const html = '<li data-sarana-pii-example>NIC: 999999999999</li><p>real content</p>';
    expect(findPii(visibleText(html))).toEqual([]);
  });

  it('does not strip an unmarked element that happens to look similar', () => {
    const html = '<li>NIC: 199712345670</li>';
    expect(names(visibleText(html))).toContain('NIC (new format, 12 digits)');
  });

  it('stripExamples removes only the marked element', () => {
    const html = '<p data-sarana-pii-example>hidden</p><p>kept</p>';
    const stripped = stripExamples(html);
    expect(stripped).not.toContain('hidden');
    expect(stripped).toContain('kept');
  });
});

describe('visibleText', () => {
  it('drops script and style bodies so the flight payload is swept separately', () => {
    const html = '<script>var nic="199712345670"</script><style>.a{}</style><p>text</p>';
    expect(visibleText(html).trim()).toBe('text');
  });
});
