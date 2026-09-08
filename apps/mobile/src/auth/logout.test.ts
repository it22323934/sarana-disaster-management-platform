/**
 * Signing out with work on the device.
 *
 * The rule the brief states without qualification: **never log a user out while unsynced
 * operations exist.** Signing out clears the tokens, so an officer with forty unsynced
 * assessments who taps Sign out at the end of a shift would get a login screen as
 * confirmation that a day's fieldwork is gone.
 */

import { describe, expect, it } from 'vitest';

import { mayLogOut } from './logout.js';

describe('mayLogOut', () => {
  it('allows sign-out when everything has reached the server', () => {
    expect(mayLogOut({ unsyncedCount: 0, attentionCount: 0 })).toEqual({ allowed: true });
  });

  it('refuses while a single operation is unsynced', () => {
    // One is enough. There is no threshold below which losing a household's assessment
    // is acceptable.
    const verdict = mayLogOut({ unsyncedCount: 1, attentionCount: 0 });
    expect(verdict.allowed).toBe(false);
  });

  it('names the number, because a vague warning is a dismissed warning', () => {
    const verdict = mayLogOut({ unsyncedCount: 40, attentionCount: 0 });
    if (verdict.allowed) throw new Error('expected a refusal');
    expect(verdict.messageKey).toBe('auth.logout.blocked');
    expect(verdict.values).toEqual({ count: 40, attention: 0 });
  });

  it('says so differently when some of the work needs a person', () => {
    // "Sync now" will not clear a conflict, so offering only that would send the officer
    // round a loop. The message and the offers both change.
    const verdict = mayLogOut({ unsyncedCount: 12, attentionCount: 2 });
    if (verdict.allowed) throw new Error('expected a refusal');
    expect(verdict.messageKey).toBe('auth.logout.blockedWithAttention');
    expect(verdict.offers).toContain('force-sign-out');
  });

  it('offers only actions that move the work, never a plain dismiss', () => {
    const verdict = mayLogOut({ unsyncedCount: 5, attentionCount: 0 });
    if (verdict.allowed) throw new Error('expected a refusal');
    expect(verdict.offers).toEqual(['sync-now', 'export-queue']);
  });

  it('lets a user out once they have acknowledged the loss', () => {
    // There has to be a way out: a device being handed to a different officer, or one
    // whose conflicts can only be resolved in the district office, cannot be locked to a
    // session forever. It is deliberately not a single tap.
    expect(
      mayLogOut({ unsyncedCount: 40, attentionCount: 3, acknowledgedDataLoss: true }),
    ).toEqual({ allowed: true });
  });
});
