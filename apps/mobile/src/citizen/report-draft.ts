/**
 * The emergency report, as it is written on the device.
 *
 * The thirty-second target lives here in the shape of what is *not* required: a report
 * with only a location and a type is valid and dispatchable. Every other field is
 * optional, and the flow never blocks on one.
 *
 * The field that matters most is the one that is allowed to be absent. "Anyone in
 * danger?" produces `null` when the person does not know, never `0` and never a guess.
 * An unknown the system knows is unknown is far more useful to a dispatcher than a
 * fabricated 3, because it can be asked about; a fabricated number cannot be distinguished
 * from a counted one.
 */

import { deviceUuid7 } from '../offline/ids.js';
import type { Database } from '../offline/db/types.js';
import type { OperationLog } from '../offline/log/operation-log.js';

/**
 * Six on the first screen, no more.
 *
 * Chosen as the six a person is most likely to be reporting when they open this app in a
 * hurry, not as a taxonomy. Anything else is `OTHER` plus a voice note, which is faster
 * for the reporter and no worse for the dispatcher than a wrong category would be.
 */
export const INCIDENT_TYPES = [
  'FLOOD',
  'TRAPPED',
  'MEDICAL',
  'STRUCTURAL',
  'LANDSLIDE',
  'OTHER',
] as const;

export type IncidentType = (typeof INCIDENT_TYPES)[number];

export type LocationSource = 'gps' | 'cell' | 'manual' | 'inferred';

export interface ReportLocation {
  readonly latitude: number;
  readonly longitude: number;
  readonly accuracyMetres: number | null;
  readonly source: LocationSource;
}

export interface ReportDraft {
  readonly incidentType: IncidentType | null;
  readonly text: string | null;
  readonly language: 'si' | 'ta' | 'en';
  readonly location: ReportLocation | null;
  /**
   * How many people are in danger.
   *
   * `null` means the reporter said they did not know. It is a different answer from
   * zero and the two must never be conflated on the way to the server.
   */
  readonly peopleAtRisk: number | null;
}

export class ReportRefused extends Error {}

/**
 * Whether this draft can be submitted.
 *
 * Deliberately almost nothing. The only refusal is a report with no type, no text, no
 * location and no media - which is an accidental tap, not a report, and sending it would
 * put an empty row in a dispatcher's queue during the hour they can least afford one.
 */
export function isSubmittable(
  draft: ReportDraft,
  { mediaCount = 0 }: { mediaCount?: number } = {},
): boolean {
  return (
    draft.incidentType !== null ||
    (draft.text ?? '').trim().length > 0 ||
    draft.location !== null ||
    mediaCount > 0
  );
}

/**
 * The body `POST /api/v1/reports` takes.
 *
 * `lat` and `lng` go together or not at all - incident-svc refuses one without the other,
 * and finding that out after a sync would be finding it out too late. `people_at_risk` is
 * omitted rather than sent as null, because the server's field is optional and an absent
 * key and an explicit null mean the same thing to it while only one of them survives a
 * strict validator.
 */
export function toWirePayload(draft: ReportDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    channel: 'APP',
    language: draft.language,
  };

  if (draft.incidentType !== null) payload.incident_type = draft.incidentType;
  if ((draft.text ?? '').trim().length > 0) payload.text = draft.text!.trim();

  if (draft.location !== null) {
    payload.lat = draft.location.latitude;
    payload.lng = draft.location.longitude;
    payload.location_source = draft.location.source;
    if (draft.location.accuracyMetres !== null) {
      // The server takes an integer and rejects a zero. A GPS fix that claims sub-metre
      // accuracy on a handset is wrong anyway, so it floors at one.
      payload.location_accuracy_m = Math.max(1, Math.round(draft.location.accuracyMetres));
    }
  }

  if (draft.peopleAtRisk !== null) payload.people_at_risk = draft.peopleAtRisk;

  return payload;
}

export interface SavedReport {
  readonly localId: string;
  readonly clientOperationId: string;
  /** Shown immediately, before any sync. What the person quotes when they call. */
  readonly reference: string;
}

/**
 * A reference the person can read back over a phone line.
 *
 * Crockford base32 without I, L, O or U, so a code cannot be misread aloud or mistyped
 * from a printed slip - the same alphabet `sarana_shared.domain.ids.short_code` uses for
 * the server's public references. The device's own code is prefixed `LOC` until the
 * server issues one, so nobody mistakes a queued report for a filed one.
 */
const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

export function localReference(seed: string = deviceUuid7()): string {
  const digits = seed.replace(/-/g, '');
  let code = '';
  for (let index = 0; index < 6; index += 1) {
    const byte = Number.parseInt(digits.slice(index * 2, index * 2 + 2), 16);
    code += CROCKFORD[byte % CROCKFORD.length];
  }
  return `LOC-${code}`;
}

/**
 * Save a report to the device. Returns as soon as SQLite has it.
 *
 * Nothing here touches the network, which is what makes the thirty-second target
 * reachable at all: on a congested cell during a flood, a round trip is most of the
 * budget. The confirmation the person sees is honest about that - "saved, will send when
 * you have signal", never a fake success.
 */
export async function saveReport(
  log: OperationLog,
  draft: ReportDraft,
  { now = Date.now() }: { now?: number } = {},
): Promise<SavedReport> {
  if (!isSubmittable(draft)) {
    throw new ReportRefused(
      'a report needs at least a type, a location, some text or a photo. An empty one ' +
        'would sit in a dispatcher queue during the hour they can least afford it.',
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
          draft.location?.accuracyMetres === null || draft.location === null
            ? null
            : Math.max(1, Math.round(draft.location.accuracyMetres)),
          draft.location?.source ?? null,
          draft.peopleAtRisk,
          'APP',
          new Date(now).toISOString(),
          'QUEUED',
        ],
      );
    },
  );

  return { localId, clientOperationId: record.client_operation_id, reference };
}
