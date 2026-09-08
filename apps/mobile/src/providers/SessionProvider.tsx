/**
 * Who is signed in, and what they may reach.
 *
 * One binary, two surfaces. A GN officer lands in the Field Companion and can switch to
 * the citizen app in one tap, because an officer whose own house is flooding must not
 * have to sign out to report it.
 *
 * Sign-out is the interesting operation here, not sign-in: it is refused while unsynced
 * operations exist, because clearing the session clears the tokens and a device with
 * forty unsynced assessments and no session has forty assessments nobody will ever read.
 */

import Constants from 'expo-constants';
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { SaranaClient } from '@sarana/ts-shared';

import { capabilityStore, SecureTokenStore } from '../auth/secure-token-store.js';
import type { CapabilityToken } from '../auth/capability.js';
import { mayLogOut, type LogoutVerdict } from '../auth/logout.js';
import { landingSurface, type Role, type Session, type Surface } from '../auth/session.js';
import { HttpSyncTransport } from '../offline/sync/http-transport.js';
import type { SyncTransport } from '../offline/sync/transport.js';
import { useLocale } from './LocaleProvider.js';

interface Extra {
  readonly saranaApiUrl?: string;
  readonly saranaObjectStoreUrl?: string | null;
}

const extra = (Constants.expoConfig?.extra ?? {}) as Extra;

interface SessionContextValue {
  readonly session: Session | null;
  readonly surface: Surface;
  readonly setSurface: (surface: Surface) => void;
  readonly capability: CapabilityToken | null;
  readonly client: SaranaClient;
  readonly transport: SyncTransport | null;
  readonly signIn: (session: Session) => void;
  /**
   * Attempt to sign out.
   *
   * Returns the verdict rather than a boolean, so the caller can render the refusal with
   * the count in it. `mayLogOut` is pure and tested; this only supplies the counts.
   */
  readonly attemptSignOut: (input: {
    unsyncedCount: number;
    attentionCount: number;
    acknowledgedDataLoss?: boolean;
  }) => Promise<LogoutVerdict>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

const tokens = new SecureTokenStore();

export function SessionProvider({ children }: { children: ReactNode }) {
  const { locale } = useLocale();
  const [session, setSession] = useState<Session | null>(null);
  const [surface, setSurface] = useState<Surface>('citizen');
  const [capability, setCapability] = useState<CapabilityToken | null>(null);

  useEffect(() => {
    void capabilityStore.read().then(setCapability);
  }, []);

  const client = useMemo(
    () =>
      new SaranaClient({
        baseUrl: extra.saranaApiUrl ?? 'http://localhost:8001',
        tokenStore: tokens,
        locale,
        onAuthenticationLost: () => setSession(null),
      }),
    [locale],
  );

  const transport = useMemo<SyncTransport | null>(
    () =>
      session === null
        ? null
        : new HttpSyncTransport({
            client,
            objectStoreBaseUrl: extra.saranaObjectStoreUrl ?? null,
          }),
    [client, session],
  );

  const signIn = useCallback((next: Session) => {
    setSession(next);
    setSurface(landingSurface(next));
  }, []);

  const attemptSignOut = useCallback<SessionContextValue['attemptSignOut']>(async (input) => {
    const verdict = mayLogOut(input);
    if (!verdict.allowed) return verdict;

    await tokens.clear();
    // The capability token is deliberately *not* cleared. It outlives the session: it is
    // the credential a GN officer carries into a division with no signal, and clearing it
    // on sign-out would strand them at the start of the next shift.
    setSession(null);
    setSurface('citizen');
    return verdict;
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({
      session,
      surface,
      setSurface,
      capability,
      client,
      transport,
      signIn,
      attemptSignOut,
    }),
    [attemptSignOut, capability, client, session, signIn, surface, transport],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession must be used inside a SessionProvider');
  return value;
}

export type { Role, Session, Surface };
