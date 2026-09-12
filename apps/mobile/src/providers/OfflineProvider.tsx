/**
 * The offline core, wired into React.
 *
 * Everything below this provider reads from the device database. Nothing below it reads
 * from the network directly - a screen that fetches is a screen that shows a spinner in
 * a valley, and there is no screen in this app that is allowed to do that.
 *
 * The provider also owns the three triggers that need a component tree: app foreground,
 * the initial start-up sync, and the periodic status refresh that keeps the strip honest
 * while a batch is in flight.
 */

import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { AppState } from 'react-native';

import { openDeviceDatabase } from '../offline/db/expo-database.js';
import type { Database } from '../offline/db/types.js';
import { MediaQueue } from '../offline/media/queue.js';
import { EMPTY_COUNTS, OperationLog, type LogCounts } from '../offline/log/operation-log.js';
import { EMPTY_MEDIA } from '../offline/media/queue.js';
import { statusStrip, type MediaCounts, type StatusStrip } from '../offline/status/model.js';
import { registerBackgroundSync, setEngineForBackgroundSync } from '../offline/sync/background.js';
import { OFFLINE, type NetworkState } from '../offline/sync/connectivity.js';
import { SyncEngine, type SyncEngineState } from '../offline/sync/engine.js';
import { ExpoNetworkMonitor } from '../offline/sync/expo-network-monitor.js';
import type { SyncTransport } from '../offline/sync/transport.js';
import { deviceId as readDeviceId } from '../auth/secure-token-store.js';

/**
 * How often the counts are re-read while something is happening.
 *
 * One second, and only while a sync is running or work is queued. Polling a local SQLite
 * database is cheap; polling it forever on a device with nothing to do is a battery
 * problem, and the target is a full workday of field use.
 */
const COUNT_REFRESH_MS = 1_000;

interface OfflineContextValue {
  readonly ready: boolean;
  readonly db: Database | null;
  readonly log: OperationLog | null;
  readonly media: MediaQueue | null;
  readonly engine: SyncEngine | null;
  readonly deviceId: string | null;
  readonly network: NetworkState;
  readonly counts: LogCounts;
  readonly mediaCounts: MediaCounts;
  readonly strip: StatusStrip;
  /** Re-read the counts now. Called after every write, so the strip never lags a save. */
  readonly refresh: () => void;
  readonly syncNow: () => Promise<void>;
  /** Set when the device database could not be opened. Fatal, and shown as such. */
  readonly failure: string | null;
}

const OfflineContext = createContext<OfflineContextValue | null>(null);

export interface OfflineProviderProps {
  readonly children: ReactNode;
  /**
   * The wire.
   *
   * Null until the user has signed in, because every sync endpoint is authenticated. The
   * engine is still built and still records - a device with work and no session is a
   * device that has to keep the work.
   */
  readonly transport: SyncTransport | null;
}

export function OfflineProvider({ children, transport }: OfflineProviderProps) {
  const [db, setDb] = useState<Database | null>(null);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [counts, setCounts] = useState<LogCounts>(EMPTY_COUNTS);
  const [mediaCounts, setMediaCounts] = useState<MediaCounts>(EMPTY_MEDIA);
  const [engineState, setEngineState] = useState<SyncEngineState | null>(null);
  const [tick, setTick] = useState(0);

  const log = useMemo(() => (db ? new OperationLog(db) : null), [db]);
  const media = useMemo(() => (db ? new MediaQueue(db) : null), [db]);

  const engine = useMemo(() => {
    if (!log || !media || !transport) return null;
    return new SyncEngine({ log, media, transport, network: new ExpoNetworkMonitor() });
  }, [log, media, transport]);

  const engineRef = useRef<SyncEngine | null>(null);
  engineRef.current = engine;

  // Open the database once, before anything renders text that reads from it.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const opened = await openDeviceDatabase();
        const id = await readDeviceId();
        if (cancelled) return;
        await new OperationLog(opened).register(id);
        setDb(opened);
        setDeviceId(id);
      } catch (cause) {
        if (cancelled) return;
        // Fatal and stated. An app that silently fell back to an unencrypted database, or
        // to memory, would lose a day's work without ever saying so.
        setFailure(cause instanceof Error ? cause.message : String(cause));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!engine) return;
    void engine.start();
    setEngineForBackgroundSync(engine);
    void registerBackgroundSync();
    const unsubscribe = engine.subscribe(setEngineState);
    void engine.request('startup');
    return () => {
      unsubscribe();
      setEngineForBackgroundSync(null);
      void engine.stop();
    };
  }, [engine]);

  // Foreground. The trigger that matters most in practice: an officer opens the app,
  // and by the time they have read the strip the sync has already started.
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        setTick((value) => value + 1);
        void engineRef.current?.request('foreground');
      }
    });
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    if (!log || !media) return;
    let cancelled = false;
    void (async () => {
      const [nextCounts, nextMedia] = await Promise.all([log.counts(), media.counts()]);
      if (!cancelled) {
        setCounts(nextCounts);
        setMediaCounts(nextMedia);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [log, media, tick, engineState]);

  // Only while something is happening. A device with nothing queued does not poll.
  const busy =
    (engineState?.running ?? false) ||
    counts.pending + counts.syncing + counts.blocked + mediaCounts.pending > 0;

  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setTick((value) => value + 1), COUNT_REFRESH_MS);
    return () => clearInterval(timer);
  }, [busy]);

  const value = useMemo<OfflineContextValue>(() => {
    const network = engineState?.network ?? OFFLINE;
    return {
      ready: db !== null,
      db,
      log,
      media,
      engine,
      deviceId,
      network,
      counts,
      mediaCounts,
      strip: statusStrip({
        network,
        operations: counts,
        media: mediaCounts,
        lastSyncedAt: engineState?.lastSyncedAt ?? null,
        now: Date.now(),
        progress: engineState?.progress ?? null,
      }),
      refresh: () => setTick((current) => current + 1),
      syncNow: async () => {
        await engineRef.current?.refreshNow();
        setTick((current) => current + 1);
      },
      failure,
    };
  }, [counts, db, deviceId, engine, engineState, failure, log, media, mediaCounts]);

  return <OfflineContext.Provider value={value}>{children}</OfflineContext.Provider>;
}

export function useOffline(): OfflineContextValue {
  const value = useContext(OfflineContext);
  if (!value) throw new Error('useOffline must be used inside an OfflineProvider');
  return value;
}
