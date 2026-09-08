/**
 * What the device knows about the network, and what that permits.
 *
 * Deliberately more than a boolean. "Online" on a congested 2G cell during a cyclone is
 * not the same condition as "online" on the office Wi-Fi, and the app treats them
 * differently: assessment metadata goes over both, a 4MB photo goes over one of them.
 */

export type ConnectionKind = 'wifi' | 'cellular' | 'other' | 'none' | 'unknown';

export interface NetworkState {
  /** The device has an interface up. Not a promise that anything answers. */
  readonly connected: boolean;
  /**
   * Something on the internet actually answered.
   *
   * A captive portal in an evacuation centre reports `connected: true` and swallows every
   * request, which is the case that makes a naive online check worse than none.
   */
  readonly reachable: boolean;
  readonly kind: ConnectionKind;
  /**
   * The user is paying per megabyte, or the OS says to treat it as if they are.
   *
   * Unknown on some Android builds, in which case cellular is assumed metered - the
   * expensive assumption is the safe one when the bill lands on a citizen in a disaster.
   */
  readonly metered: boolean;
}

export const OFFLINE: NetworkState = {
  connected: false,
  reachable: false,
  kind: 'none',
  metered: false,
};

/** The port. `expo-network` behind it in the app, a fake in every test. */
export interface NetworkMonitor {
  current(): Promise<NetworkState>;
  /** Fires on every change. Returns an unsubscribe. */
  subscribe(listener: (state: NetworkState) => void): () => void;
}

export type MediaPolicy = 'send' | 'defer';

export interface MediaPolicyInput {
  readonly network: NetworkState;
  /**
   * The user has said this one is urgent.
   *
   * A photo of a collapsed wall with people under it goes over 2G and the officer accepts
   * the cost. The override is per item, never a setting - a global "always upload" would
   * be switched on once and then quietly spend a citizen's data for a month.
   */
  readonly urgent?: boolean;
}

/**
 * Whether a media item may leave the device now.
 *
 * Text first, always. This function only ever decides about photos and audio; the
 * operation log is sent on any reachable connection, because 200 bytes on 2G is
 * affordable and an assessment that a reviewer cannot see is worth nothing.
 */
export function mediaPolicy({ network, urgent = false }: MediaPolicyInput): MediaPolicy {
  if (!network.reachable) return 'defer';
  if (urgent) return 'send';
  if (network.kind === 'wifi' && !network.metered) return 'send';
  return 'defer';
}

/** Whether the operation log may be sent now. */
export function maySyncText(network: NetworkState): boolean {
  return network.reachable;
}
