/**
 * The emergency report.
 *
 * The test the brief names by itself: **"I don't know" produces `null`, never `0`.** An
 * unknown the system knows is unknown can be asked about; a fabricated zero cannot be
 * distinguished from a counted one, and it is the number a dispatcher uses to decide who
 * gets a boat first.
 */

import { describe, expect, it } from 'vitest';

import {
  INCIDENT_TYPES,
  isSubmittable,
  localReference,
  toWirePayload,
  type ReportDraft,
} from './report-draft.js';

function draft(overrides: Partial<ReportDraft> = {}): ReportDraft {
  return {
    incidentType: 'FLOOD',
    text: null,
    language: 'si',
    location: { latitude: 7.2906, longitude: 80.6337, accuracyMetres: 14, source: 'gps' },
    peopleAtRisk: null,
    ...overrides,
  };
}

describe('people at risk', () => {
  it('omits the field entirely when the reporter does not know', () => {
    // Not zero, and not a guess. The absence is the answer.
    const payload = toWirePayload(draft({ peopleAtRisk: null }));
    expect('people_at_risk' in payload).toBe(false);
  });

  it('sends a real zero when the reporter says nobody', () => {
    // "Nobody is in danger, the water is in the yard" is a different report from "I have
    // no idea", and the two must not collapse into one on the wire.
    expect(toWirePayload(draft({ peopleAtRisk: 0 })).people_at_risk).toBe(0);
  });

  it('sends a counted number as given', () => {
    expect(toWirePayload(draft({ peopleAtRisk: 3 })).people_at_risk).toBe(3);
  });
});

describe('isSubmittable', () => {
  it('accepts a report with only a location and a type', () => {
    // The thirty-second target lives in what is not required. This is a valid,
    // dispatchable report.
    expect(isSubmittable(draft({ text: null }))).toBe(true);
  });

  it('accepts a report with no location at all', () => {
    // GPS indoors during a storm is often nothing. Blocking on location would refuse the
    // reports that most need to be accepted.
    expect(isSubmittable(draft({ location: null }))).toBe(true);
  });

  it('accepts a report that is only a photo', () => {
    expect(
      isSubmittable(draft({ incidentType: null, location: null, text: null }), { mediaCount: 1 }),
    ).toBe(true);
  });

  it('refuses a completely empty one', () => {
    // An accidental tap, not a report. Sending it puts an empty row in a dispatcher's
    // queue during the hour they can least afford one.
    expect(isSubmittable(draft({ incidentType: null, location: null, text: null }))).toBe(false);
  });

  it('does not count whitespace as text', () => {
    expect(
      isSubmittable(draft({ incidentType: null, location: null, text: '   \n  ' })),
    ).toBe(false);
  });
});

describe('toWirePayload', () => {
  it('sends lat and lng together or not at all', () => {
    // incident-svc refuses one without the other, and finding that out after a sync would
    // be finding it out far too late.
    const withLocation = toWirePayload(draft());
    expect(withLocation.lat).toBe(7.2906);
    expect(withLocation.lng).toBe(80.6337);

    const without = toWirePayload(draft({ location: null }));
    expect('lat' in without).toBe(false);
    expect('lng' in without).toBe(false);
  });

  it('floors GPS accuracy at one metre', () => {
    // The server takes an integer greater than zero, and a handset claiming sub-metre
    // accuracy is wrong anyway.
    const payload = toWirePayload(
      draft({ location: { latitude: 7, longitude: 80, accuracyMetres: 0.4, source: 'gps' } }),
    );
    expect(payload.location_accuracy_m).toBe(1);
  });

  it('carries the language the report was written in', () => {
    expect(toWirePayload(draft({ language: 'ta' })).language).toBe('ta');
  });

  it('always says the channel is APP', () => {
    expect(toWirePayload(draft()).channel).toBe('APP');
  });

  it('trims text and drops it when it is only whitespace', () => {
    expect(toWirePayload(draft({ text: '  water rising  ' })).text).toBe('water rising');
    expect('text' in toWirePayload(draft({ text: '   ' }))).toBe(false);
  });
});

describe('the incident types', () => {
  it('offers six and no more on the first screen', () => {
    // Six is a screen a person can read at a glance under stress. A taxonomy is not.
    expect(INCIDENT_TYPES).toHaveLength(6);
    expect(INCIDENT_TYPES).toContain('OTHER');
  });
});

describe('localReference', () => {
  it('uses an alphabet that cannot be misread aloud', () => {
    // Crockford base32: no I, L, O or U. The reference is read over a phone line and
    // copied off a printed slip.
    const reference = localReference();
    expect(reference).toMatch(/^LOC-[0-9A-HJKMNP-TV-Z]{6}$/);
  });

  it('marks a device reference as local, so it is not mistaken for a filed one', () => {
    expect(localReference()).toMatch(/^LOC-/);
  });

  it('is stable for a given seed', () => {
    const seed = '018f4a2b-0000-7000-8000-000000000001';
    expect(localReference(seed)).toBe(localReference(seed));
  });
});
