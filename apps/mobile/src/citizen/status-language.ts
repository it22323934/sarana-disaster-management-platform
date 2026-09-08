/**
 * Machine status to a sentence a frightened person can read.
 *
 * The rule from file 23: not `TRIAGED`, but "Your report has been received and
 * prioritised". Not `DISPATCH_PROPOSED`, but "A response team is being assigned". The
 * vocabulary is `incident_svc.repo.base` and it is not for citizens - it exists so a
 * dispatcher and a database can agree, and shipping it to a household is a way of saying
 * the system was not built for them.
 *
 * The second rule matters more. **Never show an ETA you are not confident in.** A missed
 * ETA during a disaster destroys trust in every subsequent message, including the ones
 * that matter more. `etaFor` returns a range or nothing, never a time.
 */

import { ATTENTION_STATUSES } from '../offline/log/types.js';

/** `incident.incident.status`, checked against the Python in test/vocabulary.test.ts. */
export const INCIDENT_STATUSES = [
  'REPORTED',
  'VERIFIED',
  'TRIAGED',
  'DISPATCHED',
  'IN_PROGRESS',
  'RESOLVED',
  'DUPLICATE',
  'REJECTED',
] as const;

export type IncidentStatus = (typeof INCIDENT_STATUSES)[number];

/** `incident.report.processing_status`. */
export const PROCESSING_STATUSES = [
  'RECEIVED',
  'TRANSCRIBING',
  'VERIFYING',
  'LINKED',
  'REJECTED',
  'HUMAN_REVIEW',
] as const;

export type ProcessingStatus = (typeof PROCESSING_STATUSES)[number];

/** Where a report is, as far as the person who filed it is concerned. */
export type CitizenStage =
  /** On the device, not yet sent. */
  | 'queued'
  /** The server has it and nobody has looked yet. */
  | 'received'
  /** Being checked, or being placed in a queue. */
  | 'assessing'
  /** A team has been assigned or is on the way. */
  | 'responding'
  /** Finished. */
  | 'resolved'
  /** Already covered by another report about the same thing. */
  | 'duplicate'
  /** Not being acted on, and the reason is shown. */
  | 'closed';

export interface ReportProgress {
  readonly stage: CitizenStage;
  /** The i18n key for the sentence. Never a raw status. */
  readonly messageKey: string;
  /**
   * Whether a response is actually moving toward the person.
   *
   * Used to decide whether to say "on the way" at all. A dispatch that has been proposed
   * but not released is not a team on the way, and telling someone it is would be the
   * single most damaging thing this screen could do.
   */
  readonly responderMoving: boolean;
}

export interface ReportState {
  /** Null while the report is still on the device. */
  readonly incidentStatus: IncidentStatus | null;
  readonly processingStatus: ProcessingStatus | null;
  /** `incident.dispatch_plan.status`. RELEASED is the only one that means anything here. */
  readonly dispatchStatus: string | null;
  /** The local operation status, for a report that has not synced. */
  readonly localStatus: string;
}

export function reportProgress(state: ReportState): ReportProgress {
  if (state.incidentStatus === null) {
    if ((ATTENTION_STATUSES as readonly string[]).includes(state.localStatus)) {
      // The device cannot send it and a person has to look. Saying "queued" here would
      // leave someone believing help is coming.
      return {
        stage: 'closed',
        messageKey: 'report.progress.stuck',
        responderMoving: false,
      };
    }
    return { stage: 'queued', messageKey: 'report.progress.queued', responderMoving: false };
  }

  switch (state.incidentStatus) {
    case 'REPORTED':
      return {
        stage: state.processingStatus === 'HUMAN_REVIEW' ? 'assessing' : 'received',
        messageKey:
          state.processingStatus === 'HUMAN_REVIEW'
            ? 'report.progress.humanReview'
            : 'report.progress.received',
        responderMoving: false,
      };
    case 'VERIFIED':
      return { stage: 'assessing', messageKey: 'report.progress.verified', responderMoving: false };
    case 'TRIAGED':
      return { stage: 'assessing', messageKey: 'report.progress.triaged', responderMoving: false };
    case 'DISPATCHED':
      // Only a RELEASED plan means a team is actually moving. A proposed or
      // awaiting-signoff plan is a dispatcher's screen, not a promise to a household.
      return state.dispatchStatus === 'RELEASED' || state.dispatchStatus === 'COMPLETED'
        ? { stage: 'responding', messageKey: 'report.progress.onTheWay', responderMoving: true }
        : { stage: 'assessing', messageKey: 'report.progress.assigning', responderMoving: false };
    case 'IN_PROGRESS':
      return { stage: 'responding', messageKey: 'report.progress.inProgress', responderMoving: true };
    case 'RESOLVED':
      return { stage: 'resolved', messageKey: 'report.progress.resolved', responderMoving: false };
    case 'DUPLICATE':
      return {
        stage: 'duplicate',
        messageKey: 'report.progress.duplicate',
        responderMoving: false,
      };
    case 'REJECTED':
      return { stage: 'closed', messageKey: 'report.progress.rejected', responderMoving: false };
  }
}

export interface EtaInput {
  /** Minutes, from the dispatch plan. Null when the plan carries none. */
  readonly estimatedMinutes: number | null;
  /** Whether the plan has actually been released. */
  readonly released: boolean;
  /**
   * How confident the estimate is, 0-1.
   *
   * From the triage agent's routing solution. It is low whenever the road network is
   * unknown, which in this build is always: OR-Tools solves against straight-line
   * distances, and file 16 says so.
   */
  readonly confidence: number;
}

/**
 * The floor below which a number is not shown at all.
 *
 * 0.7 rather than 0.5. A coin-flip estimate shown to somebody standing in water is worse
 * than silence, because silence does not make a promise.
 */
export const ETA_CONFIDENCE_FLOOR = 0.7;

export type Eta =
  | { readonly kind: 'range'; readonly lowMinutes: number; readonly highMinutes: number }
  | { readonly kind: 'none'; readonly reasonKey: string };

/**
 * What to say about arrival time.
 *
 * A range, or nothing plus a statement of the stage. Never a single time: a point estimate
 * reads as a commitment, and the difference between "20 minutes" and "20 to 40 minutes" is
 * the difference between a broken promise and a wait.
 */
export function etaFor(input: EtaInput): Eta {
  if (!input.released || input.estimatedMinutes === null) {
    return { kind: 'none', reasonKey: 'report.eta.notYetAssigned' };
  }
  if (input.confidence < ETA_CONFIDENCE_FLOOR) {
    return { kind: 'none', reasonKey: 'report.eta.notConfident' };
  }

  // +/- 40%, floored at ten minutes of width. Narrower than the routing model deserves
  // would be a false precision; wider would be useless.
  const estimate = input.estimatedMinutes;
  const spread = Math.max(5, Math.round(estimate * 0.4));
  return {
    kind: 'range',
    lowMinutes: Math.max(1, estimate - spread),
    highMinutes: estimate + spread,
  };
}
