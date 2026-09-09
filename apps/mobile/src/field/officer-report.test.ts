/**
 * A report filed by an officer on somebody's behalf.
 *
 * Two properties, and the second is the one that would be quietly lost.
 *
 *   **The record says an officer took it.** `FIELD_OFFICER` is a real channel in
 *   `incident.raw_report`'s CHECK constraint, and file 15's verification agent reads it as a
 *   documented scoring input. A report that arrived as `APP` would be treated as an
 *   anonymous citizen report and ranked below one an officer stood in front of.
 *
 *   **The officer is named, and it is not optional.** The higher confidence these reports
 *   carry is defensible only because a named civil servant was there. A report with the
 *   channel and no `reported_by` would claim the trust without the accountability.
 */

import { describe, expect, it } from 'vitest';

import { ReportRefused } from '../citizen/report-draft.js';
import { migrate } from '../offline/db/schema.js';
import { OperationLog } from '../offline/log/operation-log.js';
import { payloadOf } from '../offline/log/types.js';
import { openTestDatabase } from '../../test-support/node-database.js';
import {
  OFFICER_CHANNEL,
  isSubmittable,
  saveOfficerReport,
  toWirePayload,
  type OfficerReportDraft,
} from './officer-report.js';

const DRAFT: OfficerReportDraft = {
  incidentType: 'FLOOD',
  text: 'Water in the lane, two houses cut off.',
  language: 'en',
  location: null,
  peopleAtRisk: null,
  reporterName: 'Kamal Perera',
  reporterContact: '+94771234567',
  reportedBy: '018f4a2b-0000-7000-8000-00000000000f',
};

async function device() {
  const db = openTestDatabase();
  await migrate(db);
  const log = new OperationLog(db);
  await log.register('device-officer-01');
  return { db, log };
}

describe('the wire payload', () => {
  it('files under the officer channel the schema recognises', () => {
    // Not a flag invented on the device: `FIELD_OFFICER` is in the CHECK constraint on
    // `incident.raw_report`, alongside SMS, USSD, VOICE, APP, WEB, LORA and PARTNER_API.
    expect(toWirePayload(DRAFT)['channel']).toBe(OFFICER_CHANNEL);
    expect(OFFICER_CHANNEL).toBe('FIELD_OFFICER');
  });

  it('names the officer and marks the report as taken on behalf of a resident', () => {
    const payload = toWirePayload(DRAFT);
    expect(payload['reported_by']).toBe(DRAFT.reportedBy);
    expect(payload['on_behalf_of_citizen']).toBe(true);
  });

  it('carries the reporter details when they were given', () => {
    const payload = toWirePayload(DRAFT);
    expect(payload['reporter_name']).toBe('Kamal Perera');
    expect(payload['reporter_contact']).toBe('+94771234567');
  });

  it('omits the reporter details when they were not', () => {
    // Somebody flagging down an officer in a flooded lane may not give a name, and
    // refusing over that would lose the report. Absent, not an empty string: the server
    // can tell "not given" from "given as nothing".
    const payload = toWirePayload({ ...DRAFT, reporterName: null, reporterContact: null });
    expect('reporter_name' in payload).toBe(false);
    expect('reporter_contact' in payload).toBe(false);
  });

  it('keeps people-at-risk absent when it is unknown', () => {
    // The rule file 23 established: `null` means the reporter did not know, and it must
    // never reach the server as zero. A fabricated zero cannot be told from a counted one,
    // and it is the number that decides who gets a boat first.
    expect('people_at_risk' in toWirePayload(DRAFT)).toBe(false);
    expect(toWirePayload({ ...DRAFT, peopleAtRisk: 0 })['people_at_risk']).toBe(0);
  });
});

describe('what is refused', () => {
  it('refuses a report with no type, no text and no location', async () => {
    const { db, log } = await device();
    await expect(
      saveOfficerReport(log, { ...DRAFT, incidentType: null, text: null, location: null }),
    ).rejects.toBeInstanceOf(ReportRefused);
    await db.close();
  });

  it('refuses a report that does not name the officer', async () => {
    // The trust weighting rests on this. A report claiming the channel without the officer
    // would take the confidence and leave nobody accountable for it.
    const { db, log } = await device();
    await expect(saveOfficerReport(log, { ...DRAFT, reportedBy: '' })).rejects.toBeInstanceOf(
      ReportRefused,
    );
    await db.close();
  });

  it('accepts a report with only a location, which is often all there is', () => {
    expect(
      isSubmittable({
        ...DRAFT,
        incidentType: null,
        text: null,
        location: { latitude: 7.29, longitude: 80.63, accuracyMetres: 20, source: 'gps' },
      }),
    ).toBe(true);
  });
});

describe('saving', () => {
  it('writes the row and the operation together, with the officer channel on both', async () => {
    const { db, log } = await device();
    const saved = await saveOfficerReport(log, DRAFT);

    const [row] = await db.select<{ channel: string; public_ref: string }>(
      'SELECT channel, public_ref FROM report WHERE local_id = ?',
      [saved.localId],
    );
    expect(row?.channel).toBe(OFFICER_CHANNEL);
    // A reference the officer can read back over a radio before anything has synced.
    expect(saved.reference).toBe(row?.public_ref);

    const record = await log.byId(saved.clientOperationId);
    expect(record?.entity_type).toBe('report');
    expect(payloadOf(record!)['channel']).toBe(OFFICER_CHANNEL);

    await db.close();
  });

  it('touches no network, so it returns with the device in airplane mode', async () => {
    // Nothing in this module imports a transport. The assertion is that the save completes
    // against a database and a log alone - the officer is mid-conversation with the person
    // who just told them something, and a spinner there is a spinner in the conversation.
    const { db, log } = await device();
    const saved = await saveOfficerReport(log, DRAFT);
    expect(saved.clientOperationId).toBeTruthy();
    await db.close();
  });
});
