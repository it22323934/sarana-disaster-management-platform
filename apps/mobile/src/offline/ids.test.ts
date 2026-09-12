/**
 * Device identifiers.
 *
 * These ids are idempotency keys before they are anything else. If two operations ever
 * share one, the server treats the second as a replay of the first and one household's
 * assessment is silently discarded - so collision and ordering are what get tested here,
 * not formatting.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import { deviceUuid7, localId, resetIdState, uuid7Timestamp } from './ids.js';

beforeEach(() => {
  resetIdState();
});

describe('deviceUuid7', () => {
  it('produces a well-formed version 7 UUID', () => {
    const id = deviceUuid7();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it('never repeats an id across ten thousand calls in one millisecond', () => {
    // The realistic worst case is not ten thousand assessments; it is a retry loop that
    // mints a key per attempt. A collision there means the retry overwrites the original.
    const ids = new Set(Array.from({ length: 10_000 }, () => deviceUuid7(1_757_000_000_000)));
    expect(ids.size).toBe(10_000);
  });

  it('sorts in creation order even within one millisecond', () => {
    const ids = Array.from({ length: 500 }, () => deviceUuid7(1_757_000_000_000));
    expect([...ids].sort()).toEqual(ids);
  });

  it('keeps sorting forward when the device clock jumps backwards', () => {
    // A handset that has just picked up network time can move its clock back by minutes.
    // An id that sorted before the one written a second earlier would put an officer's
    // log out of order in the one view that is supposed to reconstruct what they did.
    const before = deviceUuid7(1_757_000_000_000);
    const after = deviceUuid7(1_757_000_000_000 - 90_000);
    expect(after > before).toBe(true);
  });

  it('advances when the clock advances', () => {
    const first = deviceUuid7(1_757_000_000_000);
    const second = deviceUuid7(1_757_000_000_050);
    expect(uuid7Timestamp(second) - uuid7Timestamp(first)).toBe(50);
  });
});

describe('uuid7Timestamp', () => {
  it('reads back the millisecond the id was minted at', () => {
    expect(uuid7Timestamp(deviceUuid7(1_757_000_123_456))).toBe(1_757_000_123_456);
  });

  it('refuses an id that is not version 7', () => {
    expect(() => uuid7Timestamp('018f4a2b-0000-4000-8000-000000000001')).toThrow(/version 7/);
  });

  it('refuses something that is not a UUID at all', () => {
    expect(() => uuid7Timestamp('not-an-id')).toThrow(/not a UUID/);
  });
});

describe('localId', () => {
  it('carries a prefix so a local row is never mistaken for a server one', () => {
    // The Field Companion shows both: drafts the device made up, and records the server
    // confirmed. A reviewer reading a support export has to be able to tell them apart.
    expect(localId('asm')).toMatch(/^asm_[0-9a-f-]{36}$/);
  });
});
