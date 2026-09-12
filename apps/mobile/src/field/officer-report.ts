/**
 * A report taken by an officer on behalf of somebody who cannot file one themselves.
 *
 * The citizen path (`citizen/report-draft.ts`) is untouched and stays the one a resident
 * uses. This is the same record with two additions the brief names — who is reporting, and
 * the fact that an officer took it — and it lives here rather than as flags on the citizen
 * draft because the citizen surface should have no way to claim `FIELD_OFFICER`.
 *
 * **`FIELD_OFFICER` is a real channel in the schema**, from `incident.raw_report`'s CHECK
 * constraint, alongside SMS, USSD, VOICE, APP, WEB, LORA and PARTNER_API. It is not a flag
 * invented on the device: incident-svc reads it, and file 15's verification agent uses it
 * as a documented scoring input.
 *
 * That scoring is the reason the screen says so out loud. An officer-taken report starts
 * with higher confidence than an anonymous one, which is defensible — a named civil servant
 * stood in front of the thing — and it is only defensible if it is visible. A weighting
 * nobody is told about is a weighting nobody can challenge.
 *
 * The reporter's name and number go into the payload and nowhere else. They are exactly
 * what `field/safe-log.ts` keeps out of logcat, and nothing here logs.
 */

import { deviceUuid7 } from '../offline/ids.js';
import type { Database } from '../offline/db/types.js';
import type { OperationLog } from '../offline/log/operation-log.js';
import {
  ReportRefused,
  localReference,
  type IncidentType,
  type ReportLocation,
  type SavedReport,
} from '../citizen/report-draft.js';

/** The channel an officer-taken report is filed under. From the schema, not invented. */
export const OFFICER_CHANNEL = 'FIELD_OFFICER';

export interface OfficerReportDraft {
  readonly incidentType: IncidentType | null;
  readonly text: string | null;
  readonly language: 'si' | 'ta' | 'en';
  readonly location: ReportLocation | null;
  readonly peopleAtRisk: number | null;
  /**
   * The person the report is about, as they gave it.
   *
   * Both optional: somebody flagging down an officer in a flooded lane may not give a name,
   * and refusing the report over that would lose it. What is never optional is the officer
   * themselves — `reportedBy` — because that is what the higher trust weighting rests on.
   */
  readonly reporterName: string | null;
  readonly reporterContact: string | null;
  /** The officer's own subject id. Required: it is who the platform is trusting. */
  readonly reportedBy: string;
}

/**
 * Whether this is a report at all.
 *
 * The same floor as the citizen path: a type, some text or a location. An officer tapping
 * Submit on an empty form has produced an accidental tap, and sending it puts a blank row
 * in a dispatcher's queue during the hour they can least afford one.
 */
export function isSubmittable(draft: OfficerReportDraft): boolean {
  return (
    draft.incidentType !== null ||
    (draft.text ?? '').trim().length > 0 ||
    draft.location !== null
  );
}

/** The payload incident-svc receives. `channel` and the two officer fields are the delta. */
export function toWirePayload(draft: OfficerReportDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    channel: OFFICER_CHANNEL,
    language: draft.language,
    reported_by: draft.reportedBy,
    on_behalf_of_citizen: true,
  };

  if (draft.incidentType !== null) payload['incident_type'] = draft.incidentType;
  if ((draft.text ?? '').trim().length > 0) payload['text'] = draft.text!.trim();
  if (draft.reporterName) payload['reporter_name'] = draft.reporterName.trim();
  if (draft.reporterContact) payload['reporter_contact'] = draft.reporterContact.trim();

  if (draft.location !== null) {
    payload['lat'] = draft.location.latitude;
    payload['lng'] = draft.location.longitude;
    payload['location_source'] = draft.location.source;
    if (draft.location.accuracyMetres !== null) {
      // The server takes an integer and rejects a zero, and a handset claiming sub-metre
      // accuracy is wrong anyway.
      payload['location_accuracy_m'] = Math.max(1, Math.round(draft.location.accuracyMetres));
    }
  }

  if (draft.peopleAtRisk !== null) payload['people_at_risk'] = draft.peopleAtRisk;

  return payload;
}

/**
 * Save an officer-taken report. Returns as soon as SQLite has it.
 *
 * No network call, for the same reason the citizen path has none: the officer is standing
 * in front of the person who just told them something, and a spinner there is a spinner in
 * the middle of a conversation.
 */
export async function saveOfficerReport(
  log: OperationLog,
  draft: OfficerReportDraft,
  { now = Date.now() }: { now?: number } = {},
): Promise<SavedReport> {
  if (!isSubmittable(draft)) {
    throw new ReportRefused(
      'a report needs at least a type, a location or some text. An empty one would sit in ' +
        'a dispatcher queue during the hour they can least afford it.',
    );
  }
  if (!draft.reportedBy) {
    throw new ReportRefused(
      'an officer-taken report has to name the officer. The higher verification confidence ' +
        'these reports carry rests on a named civil servant having been there.',
    );
  }

  const localId = `rep_${deviceUuid7(now)}`;
  const reference = localReference(localId.slice(4));
  const payload = toWirePayload(draft);

  const record = await log.append(
    { entity_type: 'report', entity_local_id: localId, op: 'create', payload },
    async (tx: Database) => {
      await tx.execute(
        'INSERT INTO report (local_id, public_ref, incident_type, text, language, latitude, ' +
          'longitude, location_accuracy_m, location_source, people_at_risk, channel, ' +
          'created_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
          localId,
          reference,
          draft.incidentType,
          draft.text,
          draft.language,
          draft.location?.latitude ?? null,
          draft.location?.longitude ?? null,
          draft.location?.accuracyMetres ?? null,
          draft.location?.source ?? null,
          draft.peopleAtRisk,
          OFFICER_CHANNEL,
          new Date(now).toISOString(),
          'QUEUED',
        ],
      );
    },
  );

  return { localId, clientOperationId: record.client_operation_id, reference };
}
