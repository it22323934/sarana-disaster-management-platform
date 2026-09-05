'use client';

/**
 * The situation map: incidents on MapLibre.
 *
 * **One layer, because one layer has data.** The brief specifies five — division
 * boundaries shaded by impact class, incident points, shelters, responder positions and a
 * delivery-gap shading — and the design system has pure builders for four of them. Only
 * the incident layer is drawn, because only incidents currently reach the console with
 * coordinates on them. The rest are named on screen as not built rather than offered as
 * toggles that do nothing, since an operator who switches on "delivery gaps" and sees an
 * unchanged map concludes there are none.
 *
 * **An incident with no coordinate is not placed on the map.** It is real — a phone call
 * naming a village and nothing more — and it stays in the queue and in the accessible
 * list, with the count of unplaceable rows shown under the map. Putting it at the division
 * centroid would invent a precision the report does not have, and putting it at (0, 0)
 * would drop it in the Gulf of Guinea.
 *
 * **Boundaries would be fetched per division, not in bulk.** `core-api` exposes geometry
 * one division at a time and there are roughly fourteen thousand of them, so the boundary
 * layer — when it is built — has to fetch only the divisions that have an incident in the
 * current queue. Bounded by the size of the event rather than the size of the country.
 */

import {
  Checkbox,
  MapLegend,
  MapShell,
  SeverityPill,
  incidentLayer,
  isGeoJsonSource,
} from '@sarana/ui';
import type { MapLike } from '@sarana/ui';
import type { SeverityLevel } from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { QueueRow } from '../lib/schemas';

const LAYERS_KEY = 'sarana.ops.map-layers';
const INCIDENT_SOURCE = 'sarana-incidents';

export interface LayerVisibility {
  readonly incidents: boolean;
  readonly divisions: boolean;
  readonly density: boolean;
  readonly deliveryGaps: boolean;
}

const DEFAULT_LAYERS: LayerVisibility = {
  incidents: true,
  // Off by default. Each visible division costs a request, so the operator opts in.
  divisions: false,
  density: false,
  deliveryGaps: false,
};

function readLayers(): LayerVisibility {
  if (typeof window === 'undefined') return DEFAULT_LAYERS;
  try {
    const raw = window.localStorage.getItem(LAYERS_KEY);
    if (!raw) return DEFAULT_LAYERS;
    return { ...DEFAULT_LAYERS, ...(JSON.parse(raw) as Partial<LayerVisibility>) };
  } catch {
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

  function toggle(key: keyof LayerVisibility): void {
    const next = { ...layers, [key]: !layers[key] };
    setLayers(next);
    try {
      window.localStorage.setItem(LAYERS_KEY, JSON.stringify(next));
    } catch {
      // Layer visibility is a convenience. Losing it is not worth an error message.
    }
  }

  // Memoised on `rows`, which TanStack Query keeps referentially stable between polls
  // through structural sharing. Without this the object is new on every render and the
  // `setData` effect below fires on renders that changed nothing.
  const geojson = useMemo(() => incidentsToGeoJson(rows), [rows]);
  const missing = unplaceable(rows);

  /**
   * Add the incident source and layer once the style is ready.
   *
   * The map handle is held in a ref rather than state: putting it in state would
   * re-render the whole tree on every style event, and nothing renders from it.
   *
   * `geojson` is read through a ref too, so this callback is stable. A callback that
   * changed on every poll would make `MapShell` tear the map down and rebuild it, which
   * on a map means refetching every tile.
   */
  const geojsonRef = useRef(geojson);
  geojsonRef.current = geojson;

  const onReady = useCallback((map: MapLike) => {
    mapRef.current = map;
    if (map.getSource(INCIDENT_SOURCE)) return;
    const spec = incidentLayer(INCIDENT_SOURCE, geojsonRef.current);
    map.addSource(INCIDENT_SOURCE, spec.source);
    map.addLayer(spec.layer);
  }, []);

  /**
   * Push new features on each poll.
   *
   * `setData` rather than removing and re-adding the source: re-adding throws when the id
   * already exists, and it drops the layer's paint state even when it does not. Before
   * the style has loaded there is no source yet and this is a no-op — `onReady` will add
   * it with whatever the data is by then.
   */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource(INCIDENT_SOURCE);
    if (isGeoJsonSource(source)) source.setData(geojson);
  }, [geojson]);

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
          {/* Only the layer that has data. The other three are specified in the brief and
              have builders waiting in the design system, but nothing feeds them yet - and
              a toggle that does nothing is worse than an absent one, because an operator
              who switches it on then believes they are seeing that layer. */}
          <Checkbox
            label={t('layerIncidents')}
            checked={layers.incidents}
            onCheckedChange={() => toggle('incidents')}
          />
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
    </div>
  );
}
