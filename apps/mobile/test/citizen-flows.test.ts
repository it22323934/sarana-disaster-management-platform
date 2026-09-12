/**
 * The citizen write paths, end to end on the device and out to the fake server.
 *
 * These are the cases file 23 lists that need more than a pure function: a report
 * completed with no network, a grievance raised offline, and the sync that carries both.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { saveReport, type ReportDraft } from '../src/citizen/report-draft.js';
import {
  SLA_DAYS,
  UNTRANSLATED_PREFIX,
  describe as describeGrievance,
  saveGrievance,
  GrievanceRefused,
} from '../src/citizen/grievance-draft.js';
import { AIRPLANE, WIFI } from '../test-support/fakes.js';
import { makeDevice, type Device } from '../test-support/harness.js';

let device: Device;

beforeEach(async () => {
  device = await makeDevice({ network: AIRPLANE });
});

afterEach(async () => {
  await device.close();
});

const HOUSEHOLD = '018f4a2b-0000-7000-8000-000000000001';

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

describe('a report filed with no network', () => {
  it('is saved and readable back immediately, with a reference to quote', () => {
    // The whole flow completes offline. The reference is on screen before any sync, so
    // the person has something to say when they call.
    return saveReport(device.log, draft(), { now: device.clock.now() }).then(async (saved) => {
      expect(saved.reference).toMatch(/^LOC-/);
      const rows = await device.db.select<{ public_ref: string; status: string }>(
        'SELECT public_ref, status FROM report',
      );
      expect(rows).toHaveLength(1);
      expect(rows[0]).toMatchObject({ public_ref: saved.reference, status: 'QUEUED' });
    });
  });

  it('submits with no location and no media', async () => {
    // GPS indoors during a storm is often nothing. This report is still dispatchable.
    await saveReport(device.log, draft({ location: null }), { now: device.clock.now() });
    device.network.set(WIFI);
    await device.engine.request('connectivity');
    expect(device.server.reports.size).toBe(1);
  });

  it('carries a null people-at-risk through to the server as an absent field', async () => {
    // The single most important field on this path. `null` and `0` are different answers
    // and the wire must not collapse them.
    await saveReport(device.log, draft({ peopleAtRisk: null }), { now: device.clock.now() });
    const [row] = await device.log.all();
    const payload = JSON.parse(row!.payload) as Record<string, unknown>;
    expect('people_at_risk' in payload).toBe(false);
  });

  it('reaches the server exactly once when the network returns', async () => {
    await saveReport(device.log, draft(), { now: device.clock.now() });
    device.network.set(WIFI);

    await device.engine.request('connectivity');
    await device.engine.refreshNow();

    expect(device.server.reports.size).toBe(1);
    expect(device.server.reportCalls).toBe(1);
    expect(await device.log.unsyncedCount()).toBe(0);
  });

  it('keeps its place in the queue behind an assessment written earlier', async () => {
    // One log, one sequence. The report does not jump the queue because it is urgent -
    // the ordering is what makes a replay safe, and the whole batch goes in one round trip
    // anyway.
    await device.saveAssessment();
    await saveReport(device.log, draft(), { now: device.clock.now() });
    const seqs = (await device.log.all()).map((row) => row.seq);
    expect(seqs).toEqual([1, 2]);
  });
});

describe('a grievance raised offline', () => {
  it('completes and syncs', async () => {
    const saved = await saveGrievance(
      device.log,
      {
        householdId: HOUSEHOLD,
        subjectType: 'DISBURSEMENT',
        subjectId: '018f4a2b-0000-7000-8000-0000000000dd',
        reasons: [{ si: 'ලැබී නැත', ta: 'கிடைக்கவில்லை', en: 'Not received' }],
        freeText: '',
        language: 'ta',
      },
      { now: device.clock.now() },
    );

    // The SLA the household is shown starts now, from the device.
    expect(saved.slaDueAt).toBe(device.clock.now() + SLA_DAYS.DISBURSEMENT * 86_400_000);

    device.network.set(WIFI);
    await device.engine.request('connectivity');
    expect(device.server.grievances.size).toBe(1);
    expect(await device.log.unsyncedCount()).toBe(0);
  });

  it('is never raised twice by a retry', async () => {
    // Two SLA clocks against one household, and two DS officers on one dispute.
    await saveGrievance(
      device.log,
      {
        householdId: HOUSEHOLD,
        subjectType: 'ENTITLEMENT',
        subjectId: '018f4a2b-0000-7000-8000-0000000000ee',
        reasons: [{ si: 'මුදල අඩුයි', ta: 'தொகை குறைவு', en: 'Amount too low' }],
        freeText: '',
        language: 'si',
      },
      { now: device.clock.now() },
    );

    device.network.set(WIFI);
    await device.engine.request('connectivity');
    await device.engine.refreshNow();
    expect(device.server.grievances.size).toBe(1);
    expect(device.server.grievanceCalls).toBe(1);
  });

  it('refuses one that names no record', async () => {
    await expect(
      saveGrievance(device.log, {
        householdId: HOUSEHOLD,
        subjectType: 'ASSESSMENT',
        subjectId: null,
        reasons: [],
        freeText: 'they never came',
        language: 'en',
      }),
    ).rejects.toThrow(GrievanceRefused);
  });

  it('accepts an exclusion grievance with no record, because being left out has no id', async () => {
    await expect(
      saveGrievance(device.log, {
        householdId: HOUSEHOLD,
        subjectType: 'EXCLUSION',
        subjectId: null,
        reasons: [{ si: 'තක්සේරු කර නැත', ta: 'மதிப்பிடப்படவில்லை', en: 'Never assessed' }],
        freeText: '',
        language: 'si',
      }),
    ).resolves.toBeDefined();
  });

  it('refuses an empty one', async () => {
    // It cannot be investigated and it would consume an SLA the household is entitled to.
    await expect(
      saveGrievance(device.log, {
        householdId: HOUSEHOLD,
        subjectType: 'EXCLUSION',
        subjectId: null,
        reasons: [],
        freeText: '   ',
        language: 'en',
      }),
    ).rejects.toThrow(GrievanceRefused);
  });
});

describe('the trilingual description', () => {
  it('renders chosen reasons properly in all three languages', () => {
    const description = describeGrievance({
      householdId: HOUSEHOLD,
      subjectType: 'ASSESSMENT',
      subjectId: 'a',
      reasons: [{ si: 'හානිය අඩුවෙන් සටහන්', ta: 'சேதம் குறைவாக பதிவு', en: 'Damage understated' }],
      freeText: '',
      language: 'ta',
    });
    expect(description.si).toBe('හානිය අඩුවෙන් සටහන්');
    expect(description.ta).toBe('சேதம் குறைவாக பதிவு');
    expect(description.en).toBe('Damage understated');
  });

  it('marks free text in the two languages it was not written in', () => {
    // Never the same text copied three times: a Sinhala officer reading Tamil words in
    // the Sinhala field has no way to tell it was never translated, and would answer as
    // though they had understood it.
    const description = describeGrievance({
      householdId: HOUSEHOLD,
      subjectType: 'ASSESSMENT',
      subjectId: 'a',
      reasons: [],
      freeText: 'கூரை முழுவதும் போய்விட்டது',
      language: 'ta',
    });
    expect(description.ta).toBe('கூரை முழுவதும் போய்விட்டது');
    expect(description.si).toContain(UNTRANSLATED_PREFIX);
    expect(description.en).toContain(UNTRANSLATED_PREFIX);
    expect(description.en).toContain('(ta)');
  });

  it('never leaves a language blank, which the server would refuse', () => {
    const description = describeGrievance({
      householdId: HOUSEHOLD,
      subjectType: 'EXCLUSION',
      subjectId: null,
      reasons: [{ si: 'a', ta: 'b', en: 'c' }],
      freeText: 'more',
      language: 'en',
    });
    for (const value of Object.values(description)) {
      expect(value.trim().length).toBeGreaterThan(0);
    }
  });
});
