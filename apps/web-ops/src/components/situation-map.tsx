'use client';

/**
 * The situation map.
 *
 * **Four layers, and each one is drawn only because something feeds it.** The brief
 * specifies five - division boundaries shaded by impact class, incident points, shelters,
 * responder positions and delivery-gap shading. Four now have a data path:
 *
 *   incidents    `GET /incidents/queue` returns lon/lat on every row
 *   responders   `GET /responders` returns the last reported position
 *   divisions    `GET /admin/gn-divisions/{id}/geometry`, one at a time, shaded by the
 *                impact class from `GET /impact-forecasts`
 *   gaps         drawn on the delivery panel, where an alert scopes them - see `GapMap`
 *
 * **Shelters are still named on screen as not built.** `admin.household` has no shelter
 * table and nothing supplies occupancy, so a toggle for it would be a toggle that does
 * nothing - and an operator who switches on a layer and sees an unchanged map concludes
 * there is nothing to see rather than nothing to draw.
 *
 * **Boundaries are fetched per division, bounded by the queue.** There are roughly 14,000
 * divisions and the endpoint serves one at a time, so the layer requests only the
 * divisions that have an incident in the current queue. Bounded by the size of the event
 * rather than the size of the country. It is off by default for the same reason: each
 * visible division costs a request, so the operator opts in.
 *
 * **An incident with no coordinate is not placed, and the count is shown.** It is real - a
 * phone call naming a village and nothing more - and it stays in the queue and in the
 * accessible list. Putting it at the division centroid would invent a precision the report
 * does not have; putting it at (0, 0) would drop it in the Gulf of Guinea.
 *
 * Coordinates go out **longitude first**. Latitude first puts every Sri Lankan feature in
 * the Indian Ocean off Somalia, which looks plausible enough on a zoomed-out map that
 * nobody catches it until somebody is sent there.
 */

import {
  Checkbox,
  MapLegend,
  MapShell,
  SeverityPill,
  gnDivisionLayer,
  incidentLayer,
  isGeoJsonSource,
  responderLayer,
} from '@sarana/ui';
import type { MapLike } from '@sarana/ui';
import type { SeverityLevel } from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useDivisionGeometries, useGNDivisionsByCode, useImpactForecasts, useResponders } from '../lib/queries';
import type { ImpactForecast, QueueRow, Responder } from '../lib/schemas';

const LAYERS_KEY = 'sarana.ops.map-layers';
const INCIDENT_SOURCE = 'sarana-incidents';
const RESPONDER_SOURCE = 'sarana-responders';
const DIVISION_SOURCE = 'sarana-divisions';

export interface LayerVisibility {
  readonly incidents: boolean;
  readonly responders: boolean;
  readonly divisions: boolean;
}

const DEFAULT_LAYERS: LayerVisibility = {
  incidents: true,
  responders: true,
  // Off by default. Each visible division costs a geometry request, so the operator opts
  // in rather than paying for it on every page load.
  divisions: false,
};

function readLayers(): LayerVisibility {
  if (typeof window === 'undefined') return DEFAULT_LAYERS;
  try {
    const raw = window.localStorage.getItem(LAYERS_KEY);
    if (!raw) return DEFAULT_LAYERS;
    return { ...DEFAULT_LAYERS, ...(JSON.parse(raw) as Partial<LayerVisibility>) };
  } catch {
    // A private window, cleared storage, or a browser blocking site data. The defaults are
    // a complete answer, so this is not worth surfacing.
    return DEFAULT_LAYERS;
  }
}

/**
 * The incident rows that can be drawn, as GeoJSON.
 *
 * Exported so a test can assert the filtering without a WebGL context. `severity` is
 * carried as a feature property because that is what `severityColourExpression` reads —
 * the colour is decided by the ramp in the design system, not by anything here.
 */
export function incidentsToGeoJson(rows: readonly QueueRow[]): {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    id: string;
    geometry: { type: 'Point'; coordinates: [number, number] };
    properties: { severity: number; public_ref: string; people_at_risk: number };
  }>;
} {
  return {
    type: 'FeatureCollection',
    features: rows
      .filter(
        (row): row is QueueRow & { lon: number; lat: number } =>
          row.lon !== null && row.lat !== null,
      )
      .map((row) => ({
        type: 'Feature' as const,
        id: row.id,
        geometry: { type: 'Point' as const, coordinates: [row.lon, row.lat] },
        properties: {
          severity: row.severity,
          public_ref: row.public_ref,
          people_at_risk: row.people_at_risk,
        },
      })),
  };
}

/**
 * Responder positions, carrying availability rather than severity.
 *
 * A responder has no severity. Colouring one with the hazard ramp would say a team is
 * dangerous, so `responderLayer` reads `available` instead.
 */
export function respondersToGeoJson(responders: readonly Responder[]) {
  return {
    type: 'FeatureCollection' as const,
    features: responders
      .filter(
        (responder): responder is Responder & { lon: number; lat: number } =>
          responder.lon !== null && responder.lat !== null,
      )
      .map((responder) => ({
        type: 'Feature' as const,
        id: responder.id,
        geometry: { type: 'Point' as const, coordinates: [responder.lon, responder.lat] },
        properties: { available: responder.status === 'AVAILABLE', org: responder.org },
      })),
  };
}

/**
 * Division boundaries, shaded by forecast impact class.
 *
 * The class comes from `GET /impact-forecasts`; a division with no forecast is drawn at
 * class 0, which is what "no expected impact" looks like and is different from not being
 * drawn at all. A division whose geometry is null is not drawn: a boundary that does not
 * exist is not a boundary at zero size.
 */
export function divisionsToGeoJson(
  geometries: ReadonlyArray<{ code: string; geometry?: unknown }>,
  forecasts: readonly ImpactForecast[],
) {
  const classByCode = new Map(
    forecasts.map((forecast) => [forecast.gn_division_code, forecast.impact_class]),
  );
  return {
    type: 'FeatureCollection' as const,
    features: geometries
      .filter((entry) => entry.geometry !== null && entry.geometry !== undefined)
      .map((entry) => ({
        type: 'Feature' as const,
        id: entry.code,
        geometry: entry.geometry,
        properties: {
          severity: classByCode.get(entry.code) ?? 0,
          gn_division_code: entry.code,
        },
      })),
  };
}

/** How many rows the map cannot place. Surfaced, never silently dropped. */
export function unplaceable(rows: readonly QueueRow[]): number {
  return rows.filter((row) => row.lon === null || row.lat === null).length;
}

export interface SituationMapProps {
  readonly rows: readonly QueueRow[];
  readonly className?: string;
}

export function SituationMap({ rows, className }: SituationMapProps) {
  const t = useTranslations('cop');
  const [layers, setLayers] = useState<LayerVisibility>(DEFAULT_LAYERS);
  const mapRef = useRef<MapLike | null>(null);

  useEffect(() => setLayers(readLayers()), []);

  const responders = useResponders();

  // Only the divisions that have an incident in the current queue. This is the whole
  // reason the boundary layer is affordable at all.
  const queueDivisionCodes = useMemo(
    () => [...new Set(rows.map((row) => row.gn_division_code))],
    [rows],
  );
  const divisionRows = useGNDivisionsByCode(layers.divisions ? queueDivisionCodes : []);
  const geometries = useDivisionGeometries(divisionRows.data ?? [], layers.divisions);
  const forecasts = useImpactForecasts(undefined, 0);

  function toggle(key: keyof LayerVisibility): void {
    const next = { ...layers, [key]: !layers[key] };
    setLayers(next);
    try {
      window.localStorage.setItem(LAYERS_KEY, JSON.stringify(next));
    } catch {
      // Layer visibility is a convenience. Losing it is not worth an error message.
    }
  }

  // Memoised on data TanStack Query keeps referentially stable between polls through
  // structural sharing. Without this the objects are new on every render and the `setData`
  // effects fire on renders that changed nothing.
  const incidentGeo = useMemo(() => incidentsToGeoJson(rows), [rows]);
  const responderGeo = useMemo(
    () => respondersToGeoJson(layers.responders ? (responders.data ?? []) : []),
    [layers.responders, responders.data],
  );
  const divisionGeo = useMemo(
    () => divisionsToGeoJson(geometries.data ?? [], forecasts.data ?? []),
    [geometries.data, forecasts.data],
  );

  const missing = unplaceable(rows);
  const respondersUnplaced = (responders.data ?? []).filter(
    (responder) => responder.lon === null || responder.lat === null,
  ).length;

  const dataRef = useRef({ incidentGeo, responderGeo, divisionGeo });
  dataRef.current = { incidentGeo, responderGeo, divisionGeo };

  /**
   * Add each source once the style is ready.
   *
   * Order matters: the division fill goes on first so the points sit above it rather than
   * being covered by a translucent polygon added later.
   *
   * The map handle lives in a ref rather than state - putting it in state would re-render
   * the whole tree on every style event and nothing renders from it - and the data is read
   * through a ref so this callback is stable. A callback that changed on every poll would
   * make `MapShell` tear the map down and rebuild it, which means refetching every tile.
   */
  const onReady = useCallback((map: MapLike) => {
    mapRef.current = map;
    if (!map.getSource(DIVISION_SOURCE)) {
      const spec = gnDivisionLayer(DIVISION_SOURCE, dataRef.current.divisionGeo);
      map.addSource(DIVISION_SOURCE, spec.source);
      map.addLayer(spec.layer);
    }
    if (!map.getSource(RESPONDER_SOURCE)) {
      const spec = responderLayer(RESPONDER_SOURCE, dataRef.current.responderGeo);
      map.addSource(RESPONDER_SOURCE, spec.source);
      map.addLayer(spec.layer);
    }
    if (!map.getSource(INCIDENT_SOURCE)) {
      const spec = incidentLayer(INCIDENT_SOURCE, dataRef.current.incidentGeo);
      map.addSource(INCIDENT_SOURCE, spec.source);
      map.addLayer(spec.layer);
    }
  }, []);

  /**
   * Push new features on each poll.
   *
   * `setData` rather than removing and re-adding the source: re-adding throws when the id
   * already exists, and it drops the layer's paint state even when it does not. Before the
   * style has loaded there is no source yet and this is a no-op — `onReady` adds it with
   * whatever the data is by then.
   *
   * A hidden layer is fed an empty collection rather than removed. Removing a layer and
   * re-adding it loses its paint state and its position in the draw order, so a toggle
   * would silently change how the map looks the second time it is switched on.
   */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const [id, data] of [
      [INCIDENT_SOURCE, layers.incidents ? incidentGeo : EMPTY_COLLECTION],
      [RESPONDER_SOURCE, responderGeo],
      [DIVISION_SOURCE, layers.divisions ? divisionGeo : EMPTY_COLLECTION],
    ] as const) {
      const source = map.getSource(id);
      if (isGeoJsonSource(source)) source.setData(data);
    }
  }, [incidentGeo, responderGeo, divisionGeo, layers.incidents, layers.divisions]);

  const styleUrl = process.env.NEXT_PUBLIC_SARANA_MAP_STYLE_URL ?? '';
  const present = [...new Set(rows.map((row) => row.severity))].sort() as SeverityLevel[];

  return (
    <div className={className}>
      {/* `min-h-0` and `flex-1` so the map takes the space left over rather than all of
          it. Without them the map is `h-full` inside a flex column and the controls below
          are pushed out of an `overflow-hidden` parent - clipped, not scrolled, so the
          unplaceable count silently disappears. */}
      <div className="min-h-0 flex-1">
        <MapShell
          styleUrl={styleUrl}
          label={t('map')}
          onReady={onReady}
          className="h-full w-full"
          fallback={
            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-medium">{t('mapFallback')}</h3>
              {/* The same facts as the map, as a list. Not a summary of it: this is what a
                  screen reader user, a printed situation report and a browser that failed
                  to load tiles all get. */}
              <ul className="flex flex-col gap-1">
                {rows.map((row) => (
                  <li key={row.id} className="flex items-center gap-2 text-xs">
                    <SeverityPill level={row.severity as SeverityLevel} locale="en" />
                    <span data-sarana-datum="" className="font-mono">
                      {row.gn_division_code}
                    </span>
                    <span>{row.public_ref}</span>
                    {row.lon === null || row.lat === null ? (
                      <span className="text-[var(--sev-2-fg)]">{t('noCoordinate')}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          }
        />
      </div>

      <div className="mt-2 flex shrink-0 flex-wrap items-start gap-4">
        <fieldset className="flex flex-col gap-1">
          <legend className="sr-only">{t('layers')}</legend>
          <Checkbox
            label={t('layerIncidents')}
            checked={layers.incidents}
            onCheckedChange={() => toggle('incidents')}
          />
          <Checkbox
            label={t('layerResponders')}
            checked={layers.responders}
            onCheckedChange={() => toggle('responders')}
          />
          <Checkbox
            label={t('layerDivisions')}
            description={t('layerDivisionsHint')}
            checked={layers.divisions}
            onCheckedChange={() => toggle('divisions')}
          />
          {/* Named as absent rather than offered as a toggle that does nothing. An
              operator who switches on "shelters" and sees an unchanged map concludes
              there are none, which is a different claim from "we hold no shelter data". */}
          <p className="text-2xs text-[var(--text-muted)]">{t('layersNotBuilt')}</p>
        </fieldset>

        {present.length > 0 ? (
          <MapLegend
            title={t('layers')}
            // Only the levels actually on this map. A legend listing five when three are
            // drawn invites the conclusion that the other two were checked and absent.
            levels={present}
            labels={{ 0: '0', 1: '1', 2: '2', 3: '3', 4: '4' }}
            className="max-w-xs"
          />
        ) : null}
      </div>

      {missing > 0 ? (
        // Never silently dropped. An incident the map cannot place is still an incident,
        // and an operator reading the map needs to know the count is not the whole queue.
        <p role="status" className="mt-2 shrink-0 text-2xs text-[var(--sev-2-fg)]">
          {t('unplaceable', { count: missing })}
        </p>
      ) : null}

      {layers.responders && respondersUnplaced > 0 ? (
        <p role="status" className="mt-1 shrink-0 text-2xs text-[var(--sev-2-fg)]">
          {t('respondersUnplaced', { count: respondersUnplaced })}
        </p>
      ) : null}
    </div>
  );
}

/** What a hidden layer is fed. See the `setData` effect for why it is not removed. */
const EMPTY_COLLECTION = { type: 'FeatureCollection' as const, features: [] };
