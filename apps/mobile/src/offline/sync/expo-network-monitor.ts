/**
 * The `expo-network` implementation of `NetworkMonitor`.
 *
 * `isInternetReachable` is the field that matters and the one a naive check leaves out.
 * An evacuation centre's Wi-Fi reports `isConnected: true` and swallows every request;
 * treating that as online burns the whole backoff budget on a link that was never going
 * to answer, and shows the officer a sync that never finishes.
 */

import * as Network from 'expo-network';

import type { ConnectionKind, NetworkMonitor, NetworkState } from './connectivity.js';

function kindOf(type: Network.NetworkStateType | undefined): ConnectionKind {
  switch (type) {
    case Network.NetworkStateType.WIFI:
      return 'wifi';
    case Network.NetworkStateType.CELLULAR:
      return 'cellular';
    case Network.NetworkStateType.NONE:
    case Network.NetworkStateType.UNKNOWN:
    case undefined:
      return 'unknown';
    default:
      return 'other';
  }
}

function toState(raw: Network.NetworkState): NetworkState {
  const kind = kindOf(raw.type);
  return {
    connected: raw.isConnected ?? false,
    // `isInternetReachable` is undefined on some Android builds. Treating undefined as
    // reachable is the right default: the alternative is an app that refuses to sync on a
    // working network because the OS declined to answer a question.
    reachable: (raw.isConnected ?? false) && (raw.isInternetReachable ?? true),
    kind,
    // The OS does not expose a metered flag through expo-network. Cellular is assumed
    // metered, which is the expensive assumption - and the safe one when the bill lands
    // on a citizen in a disaster.
    metered: kind === 'cellular',
  };
}

export class ExpoNetworkMonitor implements NetworkMonitor {
  async current(): Promise<NetworkState> {
    return toState(await Network.getNetworkStateAsync());
  }

  subscribe(listener: (state: NetworkState) => void): () => void {
    const subscription = Network.addNetworkStateListener((raw) => listener(toState(raw)));
    return () => subscription.remove();
  }
}
