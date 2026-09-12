/**
 * What a report's status is allowed to say to the person who filed it.
 *
 * Two failures are being prevented, and the second one is worse than the first. Showing
 * `DISPATCH_PROPOSED` is unhelpful. Showing "a team is on the way" when a plan has been
 * proposed and nobody has approved it is a promise the platform cannot keep, made to
 * somebody standing in water.
 */

import { describe, expect, it } from 'vitest';

import { ETA_CONFIDENCE_FLOOR, etaFor, reportProgress, type ReportState } from './status-language.js';

function state(overrides: Partial<ReportState> = {}): ReportState {
  return {
    incidentStatus: null,
    processingStatus: null,
    dispatchStatus: null,
    localStatus: 'pending',
    ...overrides,
  };
}

describe('reportProgress', () => {
  it('says it is still on the device before it syncs', () => {
    expect(reportProgress(state())).toMatchObject({
      stage: 'queued',
      messageKey: 'report.progress.queued',
      responderMoving: false,
    });
  });

  it('does not call a stuck report queued', () => {
    // A conflict or a repeated failure means it is not going anywhere without a person.
    // "Queued" would leave someone waiting for help that was never dispatched.
    expect(reportProgress(state({ localStatus: 'conflict' })).stage).toBe('closed');
    expect(reportProgress(state({ localStatus: 'failed' })).messageKey).toBe(
      'report.progress.stuck',
    );
  });

  it('never emits a raw status', () => {
    // The whole vocabulary, checked at once: every key is a sentence key, and none of them
    // is the database's word for the state.
    const statuses = [
      'REPORTED',
      'VERIFIED',
      'TRIAGED',
      'DISPATCHED',
      'IN_PROGRESS',
      'RESOLVED',
      'DUPLICATE',
      'REJECTED',
    ] as const;
    for (const status of statuses) {
      const progress = reportProgress(state({ incidentStatus: status }));
      expect(progress.messageKey).toMatch(/^report\.progress\./);
      expect(progress.messageKey).not.toContain(status);
    }
  });

  it('only says a team is on the way once the plan is released', () => {
    // The dispatch gate is the point at which a response becomes real. Before it, a plan
    // is a dispatcher's screen; after it, a team is moving.
    expect(
      reportProgress(state({ incidentStatus: 'DISPATCHED', dispatchStatus: 'PROPOSED' })),
    ).toMatchObject({ stage: 'assessing', responderMoving: false });

    expect(
      reportProgress(state({ incidentStatus: 'DISPATCHED', dispatchStatus: 'AWAITING_SIGNOFF' }))
        .responderMoving,
    ).toBe(false);

    expect(
      reportProgress(state({ incidentStatus: 'DISPATCHED', dispatchStatus: 'RELEASED' })),
    ).toMatchObject({ stage: 'responding', responderMoving: true });
  });

  it('treats an approved-but-not-released plan as still being assigned', () => {
    // APPROVED is one signature short of RELEASED. Close is not moving.
    expect(
      reportProgress(state({ incidentStatus: 'DISPATCHED', dispatchStatus: 'APPROVED' }))
        .responderMoving,
    ).toBe(false);
  });

  it('has a distinct sentence for a report held for human review', () => {
    // Low-confidence transcription. The person deserves to know it is being read by
    // somebody rather than that nothing has happened.
    expect(
      reportProgress(state({ incidentStatus: 'REPORTED', processingStatus: 'HUMAN_REVIEW' })),
    ).toMatchObject({ stage: 'assessing', messageKey: 'report.progress.humanReview' });
  });

  it('says a duplicate is covered, not that it was ignored', () => {
    expect(reportProgress(state({ incidentStatus: 'DUPLICATE' })).stage).toBe('duplicate');
  });
});

describe('etaFor', () => {
  it('shows nothing at all before a plan is released', () => {
    expect(etaFor({ estimatedMinutes: 20, released: false, confidence: 1 })).toEqual({
      kind: 'none',
      reasonKey: 'report.eta.notYetAssigned',
    });
  });

  it('shows nothing when the routing is not confident', () => {
    // The triage agent solves against straight-line distances - there is no road network
    // in this build - so a low-confidence estimate is the normal case, not an edge one.
    expect(
      etaFor({ estimatedMinutes: 20, released: true, confidence: ETA_CONFIDENCE_FLOOR - 0.01 }),
    ).toEqual({ kind: 'none', reasonKey: 'report.eta.notConfident' });
  });

  it('shows a range, never a single time', () => {
    // A point estimate reads as a commitment. The difference between "20 minutes" and
    // "12 to 28 minutes" is the difference between a broken promise and a wait.
    const eta = etaFor({ estimatedMinutes: 20, released: true, confidence: 0.9 });
    expect(eta).toEqual({ kind: 'range', lowMinutes: 12, highMinutes: 28 });
  });

  it('never offers a range narrower than the model deserves', () => {
    // A five-minute estimate would otherwise become "4 to 6 minutes", which is a precision
    // straight-line routing cannot support.
    expect(etaFor({ estimatedMinutes: 5, released: true, confidence: 0.95 })).toEqual({
      kind: 'range',
      lowMinutes: 1,
      highMinutes: 10,
    });
  });

  it('shows nothing when the plan carries no estimate', () => {
    expect(etaFor({ estimatedMinutes: null, released: true, confidence: 1 }).kind).toBe('none');
  });
});
