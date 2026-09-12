/**
 * The provider stack, in the order the dependencies actually run.
 *
 *   Locale   - above everything, because the sign-in screen is a citizen-facing string
 *     Session  - owns the API client, which needs the locale for Accept-Language
 *       Offline  - owns the database and the sync engine, which need the transport
 *         Query    - caches reads, persisted so a cold start with no signal still renders
 *
 * The nesting is not arbitrary and reversing any two levels breaks something specific,
 * which is why it is written down here rather than left to be inferred from the file.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { QueryClient } from '@tanstack/react-query';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { useMemo } from 'react';
import type { ReactNode } from 'react';

import { LocaleProvider } from './LocaleProvider.js';
import { OfflineProvider } from './OfflineProvider.js';
import { SessionProvider, useSession } from './SessionProvider.js';

/** A week. A device that has been in a cut-off division for six days still renders. */
const CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Long, because everything important is in SQLite and the cache is for reference
        // data - divisions, households, the damage schedule - that changes weekly at most.
        staleTime: 5 * 60_000,
        gcTime: CACHE_MAX_AGE_MS,
        // Retries are the sync engine's job, with its own backoff. A query that retries
        // three times on a dead network just spends battery arriving at the same answer.
        retry: 1,
        refetchOnReconnect: true,
        refetchOnWindowFocus: false,
        networkMode: 'offlineFirst',
      },
    },
  });
}

/** The Offline provider needs the transport, which the Session provider owns. */
function OfflineFromSession({ children }: { children: ReactNode }) {
  const { transport } = useSession();
  return <OfflineProvider transport={transport}>{children}</OfflineProvider>;
}

export function AppProviders({ children }: { children: ReactNode }) {
  const client = useMemo(makeQueryClient, []);
  const persister = useMemo(
    () => createAsyncStoragePersister({ storage: AsyncStorage, key: 'sarana.query-cache' }),
    [],
  );

  return (
    <LocaleProvider>
      <SessionProvider>
        <OfflineFromSession>
          <PersistQueryClientProvider
            client={client}
            persistOptions={{ persister, maxAge: CACHE_MAX_AGE_MS }}
          >
            {children}
          </PersistQueryClientProvider>
        </OfflineFromSession>
      </SessionProvider>
    </LocaleProvider>
  );
}

export { useLocale, useT } from './LocaleProvider.js';
export { useOffline } from './OfflineProvider.js';
export { useSession } from './SessionProvider.js';
