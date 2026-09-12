/**
 * Which phase the console says the response is in.
 *
 * The boundaries decide a word an operator reads at the top of every screen, so they are
 * pinned rather than left to a comment.
 */

import { describe, expect, it } from 'vitest';

import { offsetHours, phaseForOffsetHours } from './disaster-spine';
import { anchorEvent, type HazardEvent } from '../lib/schemas';

function event(overrides: Partial<HazardEvent> = {}): HazardEvent {
  return {
    id: '018f3c2a-0030-7e90-9c2d-000000000030',
    type: 'CYCLONE',
    name: { si: 'දිත්වා', ta: 'திட்வா', en: 'Ditwah' },
    source: 'DEPT_METEOROLOGY',
    source_ref: 'DM-2025-11-27',
    declared_at: '2025-11-25T00:00:00Z',
    landfall_at: '2025-11-28T00:00:00Z',
    status: 'ACTIVE',
    ...overrides,
  };
}

describe('phaseForOffsetHours', () => {
  it('calls the window before landfall anticipatory', () => {
    // The window the whole forecasting half of the platform exists to open.
    expect(phaseForOffsetHours(-72)).toBe('anticipatory');
    expect(phaseForOffsetHours(-0.5)).toBe('anticipatory');
  });

  it('switches to response at landfall itself, not after it', () => {
    expect(phaseForOffsetHours(0)).toBe('response');
  });

  it('stays in response for the first seventy-two hours', () => {
    expect(phaseForOffsetHours(71.9)).toBe('response');
  });

  it('becomes recovery at seventy-two hours', () => {
    expect(phaseForOffsetHours(72)).toBe('recovery');
    expect(phaseForOffsetHours(14 * 24)).toBe('recovery');
  });
});

describe('offsetHours', () => {
  it('is negative before landfall and positive after', () => {
    const landfall = '2025-11-28T00:00:00Z';
    expect(offsetHours(landfall, new Date('2025-11-27T00:00:00Z'))).toBe(-24);
    expect(offsetHours(landfall, new Date('2025-11-28T06:00:00Z'))).toBe(6);
  });
});

describe('anchorEvent', () => {
  it('picks the first event that has a landfall', () => {
    // An event under monitoring has no T+0. Anchoring the console to it would draw a rail
    // with no origin, and picking the newest regardless would anchor to a depression
    // nobody is working yet.
    const monitoring = event({ id: 'a', landfall_at: null, status: 'MONITORING' });
    const active = event({ id: 'b' });
    expect(anchorEvent([monitoring, active])?.id).toBe('b');
  });

  it('returns null when nothing has a landfall', () => {
    expect(anchorEvent([event({ landfall_at: null })])).toBeNull();
  });

  it('returns null when there are no events at all', () => {
    // The common case: no cyclone today. The spine renders nothing rather than a rail
    // anchored to an invented moment.
    expect(anchorEvent([])).toBeNull();
  });
});
