/**
 * Reading the device cache.
 *
 * Every citizen screen reads from here, not from the network. That is not a performance
 * choice: a screen that fetches is a screen that shows a spinner in a valley, and the
 * screens in this app are ones a person opens when the network is at its worst.
 *
 * The refresh path is the other direction - a background pull writes into these tables
 * and the screens re-read. Nothing renders a loading state for data it already has.
 */

import { useEffect, useState } from 'react';

import type { Database } from '../offline/db/types.js';
import type { Shelter } from './shelters.js';
import type { Locale } from '../i18n/index.js';

export interface CachedAlert {
  readonly id: string;
  readonly headline_si: string;
  readonly headline_ta: string;
  readonly headline_en: string;
  readonly body_si: string;
  readonly body_ta: string;
  readonly body_en: string;
  readonly severity: number;
  readonly hazard_type: string;
  readonly area_codes: string;
  readonly effective_from: string;
  readonly effective_to: string | null;
  readonly received_at: string;
  readonly read_at: string | null;
}

/** A localised read, so a screen never indexes into a row by string concatenation. */
export function headline(alert: CachedAlert, locale: Locale): string {
  return locale === 'si' ? alert.headline_si : locale === 'ta' ? alert.headline_ta : alert.headline_en;
}

export function body(alert: CachedAlert, locale: Locale): string {
  return locale === 'si' ? alert.body_si : locale === 'ta' ? alert.body_ta : alert.body_en;
}

export function shelterName(shelter: Shelter, locale: Locale): string {
  return locale === 'si' ? shelter.name_si : locale === 'ta' ? shelter.name_ta : shelter.name_en;
}

/**
 * Rows from a table, re-read when the query or the revision changes.
 *
 * `params` and `revision` are collapsed into one string key rather than spread into the
 * dependency array. A spread array is a variable-length dependency list, which React
 * cannot check and the lint rule cannot either - and the failure mode is a query that
 * silently stops re-running when a caller adds a parameter.
 */
function useRows<T>(
  db: Database | null,
  sql: string,
  params: readonly (string | number)[] = [],
  revision: number | string = 0,
): T[] {
  const [rows, setRows] = useState<T[]>([]);
  const key = `${sql}|${params.join('')}|${revision}`;

  useEffect(() => {
    if (!db) return;
    let cancelled = false;
    void db.select<T>(sql, params).then((result) => {
      if (!cancelled) setRows(result);
    });
    return () => {
      cancelled = true;
    };
  }, [db, key]);

  return rows;
}

/**
 * Alerts that are in force now.
 *
 * `effective_to IS NULL` counts as still in force: an alert with no end time has not been
 * cancelled, and hiding it because a field is empty would take a warning off the home
 * screen of everyone it applies to.
 */
export function useCachedAlerts(db: Database | null, now: string = new Date().toISOString()) {
  return useRows<CachedAlert>(
    db,
    'SELECT * FROM alert_cache WHERE effective_from <= ? AND (effective_to IS NULL OR effective_to > ?) ' +
      'ORDER BY severity DESC, effective_from DESC',
    [now, now],
    // Re-read on the hour, not on every render: `now` is a fresh ISO string each time and
    // would otherwise make the key change constantly.
    now.slice(0, 13),
  );
}

/** Every alert the device has seen, newest first. The inbox. */
export function useAlertHistory(db: Database | null) {
  return useRows<CachedAlert>(db, 'SELECT * FROM alert_cache ORDER BY effective_from DESC LIMIT 50');
}

export function useCachedShelters(db: Database | null) {
  return useRows<Shelter>(db, 'SELECT * FROM shelter_cache ORDER BY name_en');
}

export interface LocalReport {
  readonly local_id: string;
  readonly server_id: string | null;
  readonly public_ref: string | null;
  readonly incident_type: string | null;
  readonly text: string | null;
  readonly created_at: string;
  readonly status: string;
}

/** Everything this device has reported, newest first. */
export function useLocalReports(db: Database | null, revision = 0) {
  return useRows<LocalReport>(
    db,
    'SELECT local_id, server_id, public_ref, incident_type, text, created_at, status ' +
      'FROM report ORDER BY created_at DESC',
    [],
    revision,
  );
}
