/**
 * The paper tier: what the QR carries, what it refuses, and what it must never contain.
 *
 * The brief's fourth test case is "a paper-form QR pre-fills correctly and the record
 * carries `source: PAPER`". The pre-fill half is here; the `source` half is asserted in
 * `test/field-offline.test.ts`, where a real assessment is written.
 *
 * The privacy assertions in this file are the ones that would be easiest to lose. A printed
 * form is left on a kitchen table, dropped in a lane and photographed by whoever picks it
 * up. A QR code that resolved to a household's name or number would be a register leak with
 * legs — and it is the sort of field somebody adds later to save a lookup.
 */

import { describe, expect, it } from 'vitest';

import {
  ASSESSMENT_SOURCES,
  PAPER_FORM_VERSION,
  PaperFormUnreadable,
  decodePaperForm,
  encodePaperForm,
  mayTranscribe,
} from './paper-form.js';

const PAYLOAD = {
  version: PAPER_FORM_VERSION,
  householdReference: 'HH-LK-21-010301',
  gnDivisionCode: 'LK-2-05-020-1015',
  hazardEventId: '018f4a2b-0000-7000-8000-000000000003',
};

describe('a printed form round-trips', () => {
  it('decodes to what was encoded', () => {
    expect(decodePaperForm(encodePaperForm(PAYLOAD))).toEqual(PAYLOAD);
  });

  it('round-trips a blank form with no hazard event', () => {
    // Blank forms are printed in bulk before an event and filled during one. A decoder
    // that required the hazard id would refuse the whole stack.
    const blank = { ...PAYLOAD, hazardEventId: null };
    expect(decodePaperForm(encodePaperForm(blank))).toEqual(blank);
  });

  it('survives the whitespace a scanner adds', () => {
    expect(decodePaperForm(`  ${encodePaperForm(PAYLOAD)}\n`)).toEqual(PAYLOAD);
  });
});

describe('the code carries no personal data', () => {
  const encoded = encodePaperForm(PAYLOAD);

  it('carries only the four fields it is documented to carry, and each is what it claims', () => {
    // Asserted field by field rather than by sweeping the whole string for PII shapes.
    //
    // The first version of this test used `not.toMatch(/\d{12}/)` and failed on its own
    // fixture: the hazard event id is a UUID, whose last group is twelve digits. That is
    // the same false positive the public dashboard's PII sweep hit, and the lesson is the
    // same — a digit-run pattern cannot tell an identifier from a NIC, so the useful
    // assertion is about *which fields exist*, not about what the bytes look like.
    //
    // Pinned so a field added later has to change this test, and whoever changes it has to
    // read the paragraph above about kitchen tables.
    const parts = encoded.split('|');
    expect(parts).toHaveLength(4);

    expect(parts[0]).toBe(`SARANA:AF:${PAPER_FORM_VERSION}`);
    // A registry reference, which is meaningless without the register - and the register
    // is on the officer's encrypted device.
    expect(parts[1]).toBe(PAYLOAD.householdReference);
    expect(parts[2]).toBe(PAYLOAD.gnDivisionCode);
    // A UUID with no public resolver, exactly as on the transparency dashboard.
    expect(parts[3]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  });

  it('cannot carry a name or a contact number, because there is no field for one', () => {
    // The structural guarantee, which is stronger than a regex over the output: the
    // encoder reads four properties and a household's name is not one of them. Passing one
    // in does not put it on the paper.
    const withExtras = encodePaperForm({
      ...PAYLOAD,
      // @ts-expect-error - deliberately passing a field the payload type does not have
      name: 'Kamal Perera',
      contact: '+94771234567',
    });
    expect(withExtras).not.toContain('Kamal');
    expect(withExtras).not.toContain('771234567');
    expect(withExtras).toBe(encoded);
  });
});

describe('a code that cannot be trusted is refused, never guessed at', () => {
  it('refuses a QR from another system', () => {
    // Guessing here would pre-fill somebody else's household reference into a form the
    // officer is about to attest to.
    expect(() => decodePaperForm('https://example.com/anything')).toThrow(PaperFormUnreadable);
  });

  it('refuses a partial scan', () => {
    expect(() => decodePaperForm('SARANA:AF:1|HH-LK-21-010301')).toThrow(PaperFormUnreadable);
  });

  it('refuses a newer form version and says what to do', () => {
    const future = encodePaperForm({ ...PAYLOAD, version: PAPER_FORM_VERSION + 1 });
    try {
      decodePaperForm(future);
      expect.unreachable('a newer version must not decode');
    } catch (error) {
      expect(error).toBeInstanceOf(PaperFormUnreadable);
      expect((error as Error).message).toContain('Update the app');
    }
  });

  it('accepts an older version, because a drawer full of forms is normal', () => {
    // Forms sit in a drawer for months. Refusing an older version would strand a stack of
    // completed paperwork that has no other route into the system.
    const older = 'SARANA:AF:1|HH-LK-21-010301|LK-2-05-020-1015|';
    expect(decodePaperForm(older).version).toBe(1);
  });

  it('refuses a code missing the reference or the division', () => {
    expect(() => decodePaperForm('SARANA:AF:1||LK-2-05-020-1015|')).toThrow(PaperFormUnreadable);
    expect(() => decodePaperForm('SARANA:AF:1|HH-LK-21-010301||')).toThrow(PaperFormUnreadable);
  });

  it('keeps what it scanned, so the screen can show it', () => {
    try {
      decodePaperForm('NOT-A-SARANA-CODE');
      expect.unreachable('it must refuse');
    } catch (error) {
      expect((error as PaperFormUnreadable).scanned).toBe('NOT-A-SARANA-CODE');
    }
  });
});

describe('encoding refuses input it cannot represent', () => {
  it('refuses a reference containing the delimiter', () => {
    // A pipe in a reference would silently split into an extra field and the decoder
    // would read the division out of the wrong position.
    expect(() => encodePaperForm({ ...PAYLOAD, householdReference: 'HH|21' })).toThrow();
  });

  it('refuses an empty reference', () => {
    expect(() => encodePaperForm({ ...PAYLOAD, householdReference: '' })).toThrow();
  });
});

describe('a form from another division', () => {
  it('is refused before the officer transcribes twenty of them', () => {
    // The capability token is pinned to one division. Checked at the scan, this costs a
    // sentence; checked at sync, it is twenty transcriptions refused three days later.
    const verdict = mayTranscribe(PAYLOAD, 'LK-2-05-021-1016');
    expect(verdict.allowed).toBe(false);
    expect(verdict.reason).toContain('LK-2-05-020-1015');
    expect(verdict.reason).toContain('refused when it syncs');
  });

  it('is allowed when the divisions match', () => {
    expect(mayTranscribe(PAYLOAD, 'LK-2-05-020-1015').allowed).toBe(true);
  });
});

describe('the source vocabulary', () => {
  it('is exactly the two the schema records', () => {
    expect([...ASSESSMENT_SOURCES]).toEqual(['PHONE', 'PAPER']);
  });
});
