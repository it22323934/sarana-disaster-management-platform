/**
 * The offline capability token.
 *
 * A credential deliberately capable of almost nothing: 72 hours, one GN division, one
 * permission. If the handset is lost, what the finder gains is the ability to write
 * drafts a DS approver reviews before any of them turns into money.
 */

import { describe, expect, it } from 'vitest';

import {
  CAPABILITY_REFRESH_SKEW_MS,
  CAPABILITY_SCOPES,
  CAPABILITY_TTL_MS,
  capabilityStatus,
  fromResponse,
  permits,
  type CapabilityToken,
} from './capability.js';
import { surfacesFor, landingSurface, mayEnter } from './session.js';

const NOW = Date.UTC(2026, 8, 8, 6, 0, 0);
const DIVISION = 'LK-2-05-020-1015';

const token: CapabilityToken = {
  token: 'eyJ...',
  gnDivisionCode: DIVISION,
  deviceId: 'device-kandy-01',
  permits: ['assessment:write'],
  expiresAt: NOW + CAPABILITY_TTL_MS,
};

describe('the capability constants', () => {
  it('matches core_api.domain.auth.capability exactly', () => {
    // Asserted literally rather than derived. The two languages cannot share a module,
    // and a silent drift shows up as a token the server refuses three days into a
    // cut-off division - the worst possible moment to discover it.
    expect(CAPABILITY_TTL_MS).toBe(72 * 60 * 60 * 1000);
    expect([...CAPABILITY_SCOPES]).toEqual(['assessment:write']);
  });
});

describe('capabilityStatus', () => {
  it('accepts a live token for its own division', () => {
    const status = capabilityStatus(token, { division: DIVISION, now: NOW });
    expect(status).toMatchObject({ usable: true, renewSoon: false });
  });

  it('refuses a token for a different division', () => {
    // Checked before the officer types, not after the sync fails. A rejection three days
    // later is a rejection of work that cannot be redone.
    expect(capabilityStatus(token, { division: 'LK-1-01-002-0100', now: NOW })).toEqual({
      usable: false,
      reason: 'wrong-division',
    });
  });

  it('refuses an expired token', () => {
    expect(
      capabilityStatus(token, { division: DIVISION, now: NOW + CAPABILITY_TTL_MS + 1 }),
    ).toEqual({ usable: false, reason: 'expired' });
  });

  it('refuses when there is no token at all', () => {
    expect(capabilityStatus(null, { division: DIVISION, now: NOW })).toEqual({
      usable: false,
      reason: 'absent',
    });
  });

  it('asks to renew six hours out, not thirty seconds out', () => {
    // An officer who will be out of coverage for a day needs the token renewed on the
    // last connection they had, not on the one they were going to have.
    const nearly = NOW + CAPABILITY_TTL_MS - CAPABILITY_REFRESH_SKEW_MS + 1;
    const status = capabilityStatus(token, { division: DIVISION, now: nearly });
    expect(status).toMatchObject({ usable: true, renewSoon: true });
  });
});

describe('permits', () => {
  it('authorises drafting an assessment and nothing else', () => {
    expect(permits(token, 'assessment:write')).toBe(true);
    expect(permits(token, 'entitlement:approve')).toBe(false);
    expect(permits(token, 'disbursement:release')).toBe(false);
    expect(permits(token, 'incident:read')).toBe(false);
  });
});

describe('fromResponse', () => {
  it('turns the server ttl into an absolute expiry on the device clock', () => {
    const built = fromResponse(
      {
        capability_token: 'eyJ...',
        expires_in: 259_200,
        gn_division_code: DIVISION,
        permits: ['assessment:write'],
      },
      { deviceId: 'device-kandy-01', now: NOW },
    );
    expect(built.expiresAt).toBe(NOW + CAPABILITY_TTL_MS);
  });
});

describe('surfaces', () => {
  const officer = {
    subjectId: 'a',
    roles: ['GN_OFFICER'] as const,
    displayName: null,
    gnDivisionCode: DIVISION,
  };
  const citizen = { subjectId: 'b', roles: ['CITIZEN'] as const, displayName: null, gnDivisionCode: null };
  const approver = {
    subjectId: 'c',
    roles: ['DS_APPROVER'] as const,
    displayName: null,
    gnDivisionCode: null,
  };

  it('gives every signed-in user the citizen app', () => {
    // During a flood an officer is a citizen first. Having to sign out to report their
    // own house would be indefensible.
    expect(surfacesFor(officer)).toContain('citizen');
    expect(surfacesFor(citizen)).toEqual(['citizen']);
  });

  it('gives the Field Companion to GN officers only', () => {
    // Narrower than "anyone who can write an assessment": a DS approver reviewing their
    // own record is what the segregation rule at release time refuses.
    expect(surfacesFor(officer)).toContain('field');
    expect(surfacesFor(approver)).toEqual(['citizen']);
    expect(mayEnter(approver, 'field')).toBe(false);
  });

  it('lands an officer in the Field Companion and everyone else in the citizen app', () => {
    expect(landingSurface(officer)).toBe('field');
    expect(landingSurface(citizen)).toBe('citizen');
  });
});
