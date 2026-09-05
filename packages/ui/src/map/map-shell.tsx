'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * The MapLibre shell and the four layers the platform draws on it.
 *
 * MapLibre is an **optional peer dependency**, imported dynamically on mount. Two
 * reasons, both of which have bitten this kind of component before:
 *
 * 1. MapLibre touches `window` at module scope. A static import would crash both Next.js
 *    apps during server rendering, on every page, whether or not it showed a map.
 * 2. It is ~800KB. The citizen surfaces that never open a map should not pay for it, and
 *    a static import puts it in the shared chunk.
 *
 * The consequence is that the component renders a placeholder first and the map second,
 * so every consumer must give the container an explicit height.
 *
 * Everything here is typed structurally rather than against MapLibre's own types: the
 * package is optional, so a build without it installed must still typecheck. The shapes
 * below are the subset this shell actually calls.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react';

import { cn } from '../lib/cn.js';
import { SEVERITY, type SeverityLevel } from '../tokens/severity.js';

/**
 * A GeoJSON source, once it is on the map.
 *
 * `setData` is the only way to update a layer's features without removing and re-adding
 * the source, which throws if the id already exists and drops the layer's paint state
 * even when it does not. A console polling every fifteen seconds needs this rather than a
 * teardown.
 */
export interface GeoJsonSourceLike {
  setData(data: unknown): void;
}

/** The slice of the MapLibre map API this shell uses. */
export interface MapLike {
  on(event: string, handler: () => void): void;
  remove(): void;
  addSource(id: string, source: Record<string, unknown>): void;
  addLayer(layer: Record<string, unknown>): void;
  /** Undefined before the source is added. Narrow it before calling `setData`. */
  getSource(id: string): GeoJsonSourceLike | undefined;
  isStyleLoaded(): boolean;
}

/** Whether a source handle can take new features. Guards the `unknown` MapLibre returns. */
export function isGeoJsonSource(source: unknown): source is GeoJsonSourceLike {
  return (
    typeof source === 'object' &&
    source !== null &&
    typeof (source as GeoJsonSourceLike).setData === 'function'
  );
}

interface MapLibreModule {
  Map: new (options: Record<string, unknown>) => MapLike;
}

export interface MapShellProps {
  /** A style URL. The apps read it from `NEXT_PUBLIC_SARANA_MAP_STYLE_URL`. */
  readonly styleUrl: string;
  /** [longitude, latitude]. Defaults to the centre of Sri Lanka. */
  readonly center?: readonly [number, number];
  readonly zoom?: number;
  /**
   * Names the map region for assistive technology, e.g. "Incidents in Kandy district".
   *
   * Required. A map is a graphic that a screen reader cannot enter, so the name plus the
   * `fallback` below are the whole of its accessible content.
   */
  readonly label: string;
  /**
   * The same information, not a summary.
   *
   * A map on this platform shows which divisions are affected and how badly. That is a
   * list, and the list has to exist for anyone who cannot use the map - which includes
   * screen reader users, anyone on a connection that fails to load tiles, and anyone
   * reading a printed situation report.
   */
  readonly fallback: ReactNode;
  /** Called once the style has loaded, so layers can be added safely. */
  readonly onReady?: (map: MapLike) => void;
  readonly className?: string;
}

/** Sri Lanka's approximate centroid. */
const SRI_LANKA_CENTRE: readonly [number, number] = [80.7718, 7.8731];

export function MapShell({
  styleUrl,
  center = SRI_LANKA_CENTRE,
  zoom = 7,
  label,
  fallback,
  onReady,
  className,
}: MapShellProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLike | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading');

  useEffect(() => {
    let cancelled = false;
    const container = containerRef.current;
    if (!container) return;

    async function boot(): Promise<void> {
      let maplibre: MapLibreModule;
      try {
        // Dynamic and untyped at the import site because the package is an optional
        // peer: a workspace without it must still compile.
        maplibre = (await import('maplibre-gl')) as unknown as MapLibreModule;
      } catch {
        // No MapLibre installed, or the chunk failed to load. The fallback list is the
        // real content, so this is a degraded view rather than a broken one.
        if (!cancelled) setStatus('unavailable');
        return;
      }
      if (cancelled || !container) return;

      const map = new maplibre.Map({
        container,
        style: styleUrl,
        center: [center[0], center[1]],
        zoom,
        // The rail across the top already carries attribution for the whole page, and a
        // compact control keeps a 360px handset usable.
        attributionControl: { compact: true },
      });
      mapRef.current = map;
      map.on('load', () => {
        if (cancelled) return;
        setStatus('ready');
        onReady?.(map);
      });
      map.on('error', () => {
        if (!cancelled) setStatus('unavailable');
      });
    }

    void boot();

    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
    // `onReady` is deliberately absent from the dependency list: a caller passing an
    // inline arrow would tear down and rebuild the map on every render, which on a map
    // means refetching every tile. It is read through a ref-free closure that only ever
    // fires once per map instance, so a stale reference cannot outlive the map.
  }, [styleUrl, center, zoom]);

  return (
    <div className={cn('relative', className)}>
      <div
        ref={containerRef}
        role="application"
        aria-label={label}
        className="size-full rounded-[var(--radius-default)] bg-[var(--surface-raised)]"
      />
      {status !== 'ready' ? (
        <div className="absolute inset-0 overflow-auto rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-4">
          {fallback}
        </div>
      ) : (
        // Present even when the map has loaded, just visually hidden: the list is the
        // accessible equivalent, not a loading placeholder.
        <div className="sr-only">{fallback}</div>
      )}
    </div>
  );
}

/** Colour a MapLibre layer by the `severity` property on each feature. */
export function severityColourExpression(): unknown[] {
  const stops: unknown[] = ['match', ['get', 'severity']];
  for (const level of [0, 1, 2, 3, 4] as SeverityLevel[]) {
    stops.push(level, SEVERITY[level].base);
  }
  // MapLibre requires a fallback on `match`. Level 0 is the honest default: an
  // unclassified feature is informational, not severe.
  stops.push(SEVERITY[0].base);
  return stops;
}

export interface LayerSpec {
  readonly id: string;
  readonly source: Record<string, unknown>;
  readonly layer: Record<string, unknown>;
}

/**
 * GN division polygons, filled by severity.
 *
 * A thin outline in the divider colour rather than the severity colour: at national zoom
 * fourteen thousand coloured outlines merge into a wash that reads as one large severe
 * area.
 */
export function gnDivisionLayer(sourceId: string, data: unknown): LayerSpec {
  return {
    id: `${sourceId}-fill`,
    source: { type: 'geojson', data },
    layer: {
      id: `${sourceId}-fill`,
      type: 'fill',
      source: sourceId,
      paint: {
        'fill-color': severityColourExpression(),
        'fill-opacity': 0.45,
        'fill-outline-color': '#2A3548',
      },
    },
  };
}

/** Incident points. Sized by zoom so a cluster at national scale is still hittable. */
export function incidentLayer(sourceId: string, data: unknown): LayerSpec {
  return {
    id: `${sourceId}-points`,
    source: { type: 'geojson', data },
    layer: {
      id: `${sourceId}-points`,
      type: 'circle',
      source: sourceId,
      paint: {
        'circle-color': severityColourExpression(),
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 4, 12, 10],
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#0B1220',
      },
    },
  };
}

/**
 * Report density.
 *
 * Weighted by report count, not by severity: this layer answers "where are people
 * reporting from", which is a coverage question. Colouring it by severity would let a
 * single class-4 report light up a division nobody else has reported from.
 */
export function heatLayer(sourceId: string, data: unknown): LayerSpec {
  return {
    id: `${sourceId}-heat`,
    source: { type: 'geojson', data },
    layer: {
      id: `${sourceId}-heat`,
      type: 'heatmap',
      source: sourceId,
      paint: {
        'heatmap-weight': ['interpolate', ['linear'], ['get', 'reports'], 0, 0, 20, 1],
        'heatmap-intensity': 1,
        'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 7, 12, 12, 30],
        // Cool ramp. Density is not severity, and a warm heatmap under a severity fill
        // would put two meanings on the same hue.
        'heatmap-color': [
          'interpolate',
          ['linear'],
          ['heatmap-density'],
          0,
          'rgba(11,18,32,0)',
          0.4,
          '#0E7C86',
          1,
          '#14A0AC',
        ],
      },
    },
  };
}

/**
 * A responder's route, drawn as a line through its stops in sequence.
 *
 * `--signal`, never a severity colour. A route is a plan, not a hazard, and drawing it in
 * the severity ramp would put a class-4 red line across a map where red already means
 * something specific. The dash pattern says the same thing again for anyone who cannot
 * separate the hues.
 *
 * **Blocked segments are not drawn, because nothing supplies them.** `road_access_lost` is
 * a boolean on an incident and there is no road-network geometry anywhere in the platform,
 * so a "blocked segment" layer would be a decoration. The dispatch gate names the incidents
 * whose road access is lost in text instead, which is the true version of the same fact.
 */
export function routeLayer(sourceId: string, data: unknown): LayerSpec {
  return {
    id: `${sourceId}-route`,
    source: { type: 'geojson', data },
    layer: {
      id: `${sourceId}-route`,
      type: 'line',
      source: sourceId,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#14A0AC',
        'line-width': ['interpolate', ['linear'], ['zoom'], 7, 1.5, 12, 3.5],
        'line-dasharray': [2, 1.5],
        'line-opacity': 0.9,
      },
    },
  };
}

/**
 * Responder positions.
 *
 * A square, so it is not another circle among the incident points: two point layers in the
 * same shape are one layer as far as a glance is concerned, and a dispatcher reading this
 * map has to separate "somebody needs help here" from "a team is here" in under a second.
 *
 * Coloured by availability rather than by severity - `--verified` for available, `--pending`
 * for anything else. A responder has no severity, and borrowing the ramp for one would
 * break the rule that those five hexes mean exactly one thing.
 */
export function responderLayer(sourceId: string, data: unknown): LayerSpec {
  return {
    id: `${sourceId}-responders`,
    source: { type: 'geojson', data },
    layer: {
      id: `${sourceId}-responders`,
      type: 'circle',
      source: sourceId,
      paint: {
        'circle-color': [
          'case',
          ['==', ['get', 'available'], true],
          '#45A272',
          '#8492AF',
        ],
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 3.5, 12, 8],
        'circle-stroke-width': 2,
        'circle-stroke-color': '#E8EDF5',
      },
    },
  };
}

/**
 * Divisions shaded by how much of a warning was confirmed delivered.
 *
 * A **sequential** ramp on one hue, not the severity ramp. Low delivery confirmation is
 * not a hazard severity - it is a coverage figure, and painting a division dark red
 * because its SMS receipts have not arrived would say the hazard there is worse than in
 * the division next to it, which is the opposite of what the number means.
 *
 * The interpolation runs from `confirmed_fraction` 0 to 1, so the darkest shading is the
 * division to send a vehicle to first. Divisions with nothing targeted are not in the
 * source at all: a fraction with a zero denominator is not a low number, it is no number,
 * and shading it would report an unwarned division as an unreached one.
 */
export function deliveryGapLayer(sourceId: string, data: unknown): LayerSpec {
  return {
    id: `${sourceId}-gaps`,
    source: { type: 'geojson', data },
    layer: {
      id: `${sourceId}-gaps`,
      type: 'circle',
      source: sourceId,
      paint: {
        'circle-color': [
          'interpolate',
          ['linear'],
          ['get', 'confirmed_fraction'],
          0,
          '#5B3A7E',
          0.5,
          '#7C6AA8',
          1,
          '#D6F0F2',
        ],
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 5, 12, 14],
        'circle-opacity': 0.85,
        'circle-stroke-width': 1,
        'circle-stroke-color': '#0B1220',
      },
    },
  };
}

export interface MapLegendProps {
  /** Which levels actually appear on the map. Never the whole ramp by default. */
  readonly levels: readonly SeverityLevel[];
  readonly labels: Record<SeverityLevel, string>;
  readonly title: string;
  readonly className?: string;
}

/**
 * The legend.
 *
 * Shows only the levels present on the current map. A legend listing five levels when
 * three are drawn invites an operator to conclude that the other two were checked and
 * found absent, which is a different claim from "not shown".
 */
export function MapLegend({ levels, labels, title, className }: MapLegendProps) {
  return (
    <div
      className={cn(
        'rounded-[var(--radius-default)] border border-[var(--divider)]',
        'bg-[var(--surface-card)] p-3',
        className,
      )}
    >
      <p className="mb-2 text-2xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
        {title}
      </p>
      <ul className="flex flex-col gap-1.5">
        {levels.map((level) => (
          <li key={level} className="flex items-center gap-2 text-xs">
            <span
              aria-hidden="true"
              className="size-3 shrink-0 rounded-[2px]"
              style={{ backgroundColor: SEVERITY[level].base }}
            />
            <span className="text-[var(--text-primary)]">{labels[level]}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
