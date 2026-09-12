/**
 * What the network permits.
 *
 * The rule these tests pin is the one that costs a citizen money if it is wrong: a 4MB
 * photo does not leave the device over a metered cellular link unless a person has said
 * so about that photo.
 */

import { describe, expect, it } from 'vitest';

import { OFFLINE, maySyncText, mediaPolicy, type NetworkState } from './connectivity.js';

const wifi: NetworkState = { connected: true, reachable: true, kind: 'wifi', metered: false };
const cellular: NetworkState = {
  connected: true,
  reachable: true,
  kind: 'cellular',
  metered: true,
};
const captivePortal: NetworkState = {
  connected: true,
  reachable: false,
  kind: 'wifi',
  metered: false,
};
const meteredHotspot: NetworkState = {
  connected: true,
  reachable: true,
  kind: 'wifi',
  metered: true,
};

describe('maySyncText', () => {
  it('sends the operation log over any link something answers on', () => {
    // 200 bytes on 2G is affordable and an assessment a reviewer cannot see is worth
    // nothing, so text is never deferred for cost.
    expect(maySyncText(cellular)).toBe(true);
    expect(maySyncText(wifi)).toBe(true);
  });

  it('sends nothing with no network', () => {
    expect(maySyncText(OFFLINE)).toBe(false);
  });

  it('sends nothing behind a captive portal', () => {
    // The evacuation-centre Wi-Fi that reports connected and swallows every request. A
    // naive online check is worse than none here: it would burn the whole backoff budget
    // on a link that was never going to answer.
    expect(maySyncText(captivePortal)).toBe(false);
  });
});

describe('mediaPolicy', () => {
  it('sends photos on unmetered Wi-Fi', () => {
    expect(mediaPolicy({ network: wifi })).toBe('send');
  });

  it('defers photos on a metered cellular link', () => {
    expect(mediaPolicy({ network: cellular })).toBe('defer');
  });

  it('defers photos on a Wi-Fi hotspot the OS reports as metered', () => {
    // Someone tethering off their own phone. The interface says Wi-Fi and the bill says
    // otherwise; the bill wins.
    expect(mediaPolicy({ network: meteredHotspot })).toBe('defer');
  });

  it('sends an urgent photo over a metered link anyway', () => {
    // A collapsed wall with people under it. The officer accepts the cost, for this one
    // item - there is deliberately no global setting, because a global one gets switched
    // on once and then quietly spends a citizen's data for a month.
    expect(mediaPolicy({ network: cellular, urgent: true })).toBe('send');
  });

  it('defers even an urgent photo when nothing answers', () => {
    expect(mediaPolicy({ network: OFFLINE, urgent: true })).toBe('defer');
    expect(mediaPolicy({ network: captivePortal, urgent: true })).toBe('defer');
  });
});
