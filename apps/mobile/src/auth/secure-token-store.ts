/**
 * Tokens in the platform keystore.
 *
 * Implements `@sarana/ts-shared`'s `TokenStore`, so the shared `SaranaClient` - with its
 * single-flight refresh and its 401 retry - works on a handset unchanged. The three
 * surfaces keep tokens in three different places and this is the mobile one: Android
 * Keystore or the iOS keychain, never AsyncStorage.
 *
 * `WHEN_UNLOCKED_THIS_DEVICE_ONLY` on every item. A refresh token that travels in an
 * iCloud or Google backup is a refresh token on a machine nobody authenticated.
 */

import * as SecureStore from 'expo-secure-store';
import type { TokenPair, TokenStore } from '@sarana/ts-shared/api';

import type { CapabilityToken } from './capability.js';

const ACCESS = 'sarana.auth.tokens';
const CAPABILITY = 'sarana.auth.capability';
const DEVICE = 'sarana.auth.device';

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

async function readJson<T>(key: string): Promise<T | null> {
  const raw = await SecureStore.getItemAsync(key, OPTIONS);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    // A keystore item that will not parse is not recoverable and not worth keeping. The
    // user signs in again, which is a worse morning than it would have been and a much
    // better one than an app that cannot start.
    await SecureStore.deleteItemAsync(key, OPTIONS);
    return null;
  }
}

export class SecureTokenStore implements TokenStore {
  async read(): Promise<TokenPair | null> {
    return readJson<TokenPair>(ACCESS);
  }

  async write(tokens: TokenPair): Promise<void> {
    await SecureStore.setItemAsync(ACCESS, JSON.stringify(tokens), OPTIONS);
  }

  async clear(): Promise<void> {
    await SecureStore.deleteItemAsync(ACCESS, OPTIONS);
  }
}

/**
 * The offline capability token, kept apart from the session tokens.
 *
 * Apart, because it outlives them. Signing out clears the session; the capability token
 * is the credential a GN officer carries into a division with no signal, and clearing it
 * on sign-out would strand them. It is cleared when it expires or when the officer is
 * reassigned.
 */
export const capabilityStore = {
  async read(): Promise<CapabilityToken | null> {
    return readJson<CapabilityToken>(CAPABILITY);
  },
  async write(token: CapabilityToken): Promise<void> {
    await SecureStore.setItemAsync(CAPABILITY, JSON.stringify(token), OPTIONS);
  },
  async clear(): Promise<void> {
    await SecureStore.deleteItemAsync(CAPABILITY, OPTIONS);
  },
};

/**
 * This installation's device id.
 *
 * Minted once and kept in the keystore, not derived from a hardware identifier: Android
 * and iOS both restrict those, and a device id that changes on an OS upgrade would reset
 * the server's sync cursor and turn a device's whole log into conflicts.
 */
export async function deviceId(): Promise<string> {
  const existing = await SecureStore.getItemAsync(DEVICE, OPTIONS);
  if (existing) return existing;
  const minted = globalThis.crypto.randomUUID();
  await SecureStore.setItemAsync(DEVICE, minted, OPTIONS);
  return minted;
}
