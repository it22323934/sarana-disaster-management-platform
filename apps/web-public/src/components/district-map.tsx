'use client';

/**
 * The choropleth. The only client component on this site that ships a library.
 *
 * **It is progressive enhancement in the strict sense: the page is complete without it.**
 * The table below carries every figure this map can show, is server-rendered, and is what
 * the print stylesheet keeps. If MapLibre fails to load — a locked-down corporate proxy, a
 * CSP that blocks the tile host, a cheap phone that runs out of memory — the reader loses
 * a picture and keeps the data. That is why the map is mounted below the table's data in
 * the DOM order and why nothing on the page reads state from it.
 *
 * MapLibre is imported dynamically on mount rather than at module scope. It is roughly
 * 200 KB gzipped, and a static import would put it in the route's initial chunk and blow
 * the brief's budget on every reader, including the ones who never scroll to the map.
 *
 * The ramp is a single-hue sequential scale built from the interface accent, and it is
 * cool on purpose. Warm colours on this platform mean hazard severity and nothing else; an
 * orange district here would read as a warning level to anyone who has used the console.
 */

import { useEffect, useRef, useState } from 'react';

export interface DistrictShade {
  readonly districtCode: string;
  /** 0 to 1 after direction has been applied, or null for no data. */
  readonly position: number | null;
  /** Pre-formatted value and name, for the hover readout. */
  readonly label: string;
  readonly value: string;
}

export interface DistrictMapProps {
  readonly geojsonUrl: string;
  readonly shades: readonly DistrictShade[];
  readonly noDataLabel: string;
  readonly generatedNote: string;
  readonly title: string;
}

/**
 * The sequential ramp, as CSS colours.
 *
 * Derived from `--signal-*`: the palest is the tint the design system already uses for a
 * selected row, and the darkest is the accent at full strength. Five steps rather than a
 * continuous interpolation, because a reader matching a fill against a legend can
 * distinguish five bands and cannot distinguish a hundred.
 */
const RAMP = ['#EAF7F8', '#C3E9EC', '#8FD3D9', '#3FAEB8', '#0A5F67'] as const;
const NO_DATA_FILL = '#E4E8EE';

function fillFor(position: number | null): string {
  if (position === null) return NO_DATA_FILL;
  const index = Math.min(RAMP.length - 1, Math.max(0, Math.floor(position * RAMP.length)));
  return RAMP[index] ?? NO_DATA_FILL;
}

export function DistrictMap({
  geojsonUrl,
  shades,
  noDataLabel,
  generatedNote,
  title,
}: DistrictMapProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let map: { remove: () => void } | null = null;
    let cancelled = false;

    void (async () => {
      try {
        const maplibre = await import('maplibre-gl');
        const response = await fetch(geojsonUrl);
        if (!response.ok) throw new Error(`geojson ${response.status}`);
        const geojson = (await response.json()) as {
          features: { properties: { district_code: string } }[];
        };
        if (cancelled || !container.current) return;

        const byCode = new Map(shades.map((shade) => [shade.districtCode, shade]));
        const featureCollection = {
          ...geojson,
          features: geojson.features.map((feature) => ({
            ...feature,
            properties: {
              ...feature.properties,
              sarana_fill: fillFor(
                byCode.get(feature.properties.district_code)?.position ?? null,
              ),
            },
          })),
        };

        const instance = new maplibre.Map({
          container: container.current,
          // No tile basemap. The brief allows no third-party requests from this page, and
          // a choropleth of administrative areas does not need terrain underneath it - the
          // shapes are the content. It also means the map renders identically offline.
          style: {
            version: 8,
            sources: {},
            layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#FBFCFD' } }],
          },
          center: [80.7, 7.9],
          zoom: 6.2,
          attributionControl: false,
          // Keyboard users get the table; a map that traps arrow keys inside itself while
          // the real content is below it is worse than one that does not take focus.
          interactive: true,
        });

        instance.on('load', () => {
          instance.addSource('districts', { type: 'geojson', data: featureCollection as never });
          instance.addLayer({
            id: 'district-fill',
            type: 'fill',
            source: 'districts',
            paint: { 'fill-color': ['get', 'sarana_fill'], 'fill-opacity': 0.9 },
          });
          instance.addLayer({
            id: 'district-outline',
            type: 'line',
            source: 'districts',
            paint: { 'line-color': '#4A5A70', 'line-width': 0.6 },
          });
        });

        map = instance;
      } catch {
        // A failed map is a missing picture, not a broken page. The note replaces it and
        // points at the table, which had the same figures all along.
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
      map?.remove();
    };
  }, [geojsonUrl, shades]);

  if (failed) {
    return (
      <p className="rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-4 text-sm text-[var(--text-muted)]">
        {noDataLabel}
      </p>
    );
  }

  return (
    <figure className="m-0" data-sarana-map>
      <div
        ref={container}
        role="img"
        aria-label={title}
        className="h-[420px] w-full rounded-[var(--radius-default)] border border-[var(--divider)]"
      />
      <figcaption className="mt-2 flex flex-wrap items-center gap-3 text-xs text-[var(--text-muted)]">
        <span className="inline-flex items-center gap-1">
          {RAMP.map((colour) => (
            <span
              key={colour}
              aria-hidden="true"
              className="inline-block size-3 rounded-[1px] border border-[var(--divider)]"
              style={{ backgroundColor: colour }}
            />
          ))}
        </span>
        <span
          className="inline-flex items-center gap-1"
          // The "no data" swatch is named, not left to be inferred. A pale fill and an
          // absent fill look alike and mean opposite things.
        >
          <span
            aria-hidden="true"
            className="inline-block size-3 rounded-[1px] border border-[var(--divider)]"
            style={{ backgroundColor: NO_DATA_FILL }}
          />
          {noDataLabel}
        </span>
        <span className="max-w-prose">{generatedNote}</span>
      </figcaption>
    </figure>
  );
}
