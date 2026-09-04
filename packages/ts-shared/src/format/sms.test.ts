/**
 * The SMS segment count, and the asymmetry that makes it a life-safety concern.
 *
 * These tests pin this module against `sarana_shared.domain.sms`, which is the
 * implementation the gateway adapter actually counts with. If the two ever disagree, the
 * Python one is right and this one is the bug — so the constants are asserted literally
 * rather than derived, and the behavioural cases are the ones the Python module documents.
 */

import { describe, expect, it } from 'vitest';

import {
  GSM7_CONCATENATED,
  GSM7_SINGLE,
  MAX_SEGMENTS,
  UCS2_CONCATENATED,
  UCS2_SINGLE,
  countSegments,
  encodingFor,
  fitsInSegments,
  unitsIn,
} from './sms.js';

// Real strings, not lorem. A test that measured placeholder text would pass on a template
// that fails in production, which is the failure mode this whole module exists to prevent.
const ENGLISH = 'Evacuate to Pallekele Maha Vidyalaya now. Flood warning for Ganga Ihala Korale.';
const SINHALA = 'දැන් පල්ලේකැලේ මහා විද්‍යාලයට ඉවත් වන්න. ගඟ ඉහළ කෝරළේ සඳහා ගංවතුර අනතුරු ඇඟවීම.';
const TAMIL = 'இப்போது பள்ளேகலை மகா வித்தியாலயத்திற்கு வெளியேறுங்கள். கங்க இஹல கோரளைக்கு வெள்ள எச்சரிக்கை.';

describe('the segment constants', () => {
  it('matches the Python module exactly', () => {
    // Asserted literally rather than imported, so a drift shows up here as a failing
    // number rather than as two modules agreeing with each other and not with the gateway.
    expect(GSM7_SINGLE).toBe(160);
    expect(GSM7_CONCATENATED).toBe(153);
    expect(UCS2_SINGLE).toBe(70);
    expect(UCS2_CONCATENATED).toBe(67);
    expect(MAX_SEGMENTS).toBe(2);
  });
});

describe('encodingFor', () => {
  it('reads plain English as GSM-7', () => {
    expect(encodingFor(ENGLISH)).toBe('GSM7');
  });

  it('reads Sinhala and Tamil as UCS-2', () => {
    expect(encodingFor(SINHALA)).toBe('UCS2');
    expect(encodingFor(TAMIL)).toBe('UCS2');
  });

  it('moves the whole message to UCS-2 for a single non-GSM character', () => {
    // The trap this rule exists to name: one Sinhala letter in an otherwise English
    // message costs the same as a wholly Sinhala one. Mixed-script templates are not a
    // compromise between the two, they are the expensive one.
    expect(encodingFor('Evacuate now')).toBe('GSM7');
    expect(encodingFor('Evacuate now ට')).toBe('UCS2');
  });

  it('treats an empty message as GSM-7', () => {
    expect(encodingFor('')).toBe('GSM7');
  });
});

describe('unitsIn', () => {
  it('counts a GSM-7 extension character as two septets', () => {
    // `{`, `}`, `[`, `]`, `~`, `|`, `\` and `€` are transmitted as an escape plus the
    // character. A message full of them costs twice what its length suggests.
    expect(unitsIn('abc')).toBe(3);
    expect(unitsIn('a{c')).toBe(4);
    expect(unitsIn('€€')).toBe(4);
  });

  it('counts UCS-2 in UTF-16 code units, so an astral character costs two', () => {
    // The case where counting code points would under-count and let a message through
    // that the gateway then splits into one more part than was budgeted for.
    expect(unitsIn('\u{1F600}')).toBe(2);
  });

  it('counts Sinhala and Tamil at one unit per code unit', () => {
    expect(unitsIn(SINHALA)).toBe(SINHALA.length);
    expect(unitsIn(TAMIL)).toBe(TAMIL.length);
  });
});

describe('countSegments', () => {
  it('calls an empty message one segment, not zero', () => {
    // A gateway asked to send nothing still sends something, and reporting zero would let
    // an empty template pass a length check that exists to catch exactly the templates
    // nobody looked at.
    expect(countSegments('').segments).toBe(1);
  });

  it('charges a whole extra segment for one unit over the boundary', () => {
    expect(countSegments('a'.repeat(GSM7_SINGLE)).segments).toBe(1);
    expect(countSegments('a'.repeat(GSM7_SINGLE + 1)).segments).toBe(2);
    expect(countSegments('ට'.repeat(UCS2_SINGLE)).segments).toBe(1);
    expect(countSegments('ට'.repeat(UCS2_SINGLE + 1)).segments).toBe(2);
  });

  it('uses the concatenated size once a message is multipart', () => {
    // 153 rather than 160, because the concatenation header eats seven characters' worth
    // of every part.
    expect(countSegments('a'.repeat(GSM7_CONCATENATED * 2)).segments).toBe(2);
    expect(countSegments('a'.repeat(GSM7_CONCATENATED * 2 + 1)).segments).toBe(3);
    expect(countSegments('ට'.repeat(UCS2_CONCATENATED * 2)).segments).toBe(2);
    expect(countSegments('ට'.repeat(UCS2_CONCATENATED * 2 + 1)).segments).toBe(3);
  });

  it('reports headroom, including when it is negative', () => {
    // A template one character under the limit is one an operator will break with the next
    // place name, and the author should see that while they are still writing.
    const comfortable = countSegments('a'.repeat(100));
    expect(comfortable.headroom).toBe(GSM7_CONCATENATED * 2 - 100);

    const over = countSegments('ට'.repeat(200));
    expect(over.headroom).toBeLessThan(0);
    expect(over.withinLimit).toBe(false);
  });

  it('shows the asymmetry the whole module exists for', () => {
    // The same warning, in three languages. English fits in one segment; the other two
    // cost more, for the same sentence, because of the alphabet alone.
    const english = countSegments(ENGLISH);
    const sinhala = countSegments(SINHALA);
    const tamil = countSegments(TAMIL);

    expect(english.encoding).toBe('GSM7');
    expect(english.segments).toBe(1);
    expect(sinhala.segments).toBeGreaterThan(english.segments);
    expect(tamil.segments).toBeGreaterThan(english.segments);
  });
});

describe('fitsInSegments', () => {
  it('is the branching form of the same answer', () => {
    expect(fitsInSegments('a'.repeat(100))).toBe(true);
    expect(fitsInSegments('ට'.repeat(300))).toBe(false);
  });

  it('honours a stricter ceiling when one is asked for', () => {
    const oneSegmentOfSinhala = 'ට'.repeat(UCS2_SINGLE);
    expect(fitsInSegments(oneSegmentOfSinhala, 1)).toBe(true);
    expect(fitsInSegments(`${oneSegmentOfSinhala}ට`, 1)).toBe(false);
  });
});

/**
 * The cross-check against the Python implementation, pinned.
 *
 * These numbers were produced by running `sarana_shared.domain.sms.count` over exactly
 * these strings and copying the output. They are asserted literally so the mirror cannot
 * drift: if someone changes this module and these fail, the change is wrong, because the
 * gateway adapter counts with the Python one.
 *
 * The second and third rows are the point of the whole module - the same warning is one
 * segment in English and two in both Sinhala and Tamil, from the alphabet alone.
 */
describe('agreement with the Python implementation', () => {
  const PINNED: ReadonlyArray<
    readonly [string, { encoding: string; units: number; segments: number; headroom: number }]
  > = [
    [ENGLISH, { encoding: 'GSM7', units: 79, segments: 1, headroom: 227 }],
    [SINHALA, { encoding: 'UCS2', units: 79, segments: 2, headroom: 55 }],
    [TAMIL, { encoding: 'UCS2', units: 91, segments: 2, headroom: 43 }],
    ['', { encoding: 'GSM7', units: 0, segments: 1, headroom: 306 }],
    ['a'.repeat(160), { encoding: 'GSM7', units: 160, segments: 1, headroom: 146 }],
    ['a'.repeat(161), { encoding: 'GSM7', units: 161, segments: 2, headroom: 145 }],
    ['a{c', { encoding: 'GSM7', units: 4, segments: 1, headroom: 302 }],
    ['€€', { encoding: 'GSM7', units: 4, segments: 1, headroom: 302 }],
    ['\u{1F600}', { encoding: 'UCS2', units: 2, segments: 1, headroom: 132 }],
    ['Evacuate now ට', { encoding: 'UCS2', units: 14, segments: 1, headroom: 120 }],
  ];

  it.each(PINNED.map((row, index) => [index, row[0], row[1]] as const))(
    'agrees on case %i',
    (_index, text, expected) => {
      const actual = countSegments(text);
      expect(actual.encoding).toBe(expected.encoding);
      expect(actual.units).toBe(expected.units);
      expect(actual.segments).toBe(expected.segments);
      expect(actual.headroom).toBe(expected.headroom);
    },
  );
});
