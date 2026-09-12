'use client';

/**
 * The delivery-gap map: divisions shaded by how much of a warning was confirmed.
 *
 * Build file 20 asks the gaps panel for "a map shading by reachability confidence". Two
 * decisions in it are load-bearing and neither is about the map library.
 *
 * **A single-hue sequential ramp, never the severity ramp.** Low confirmed delivery is a
 * coverage figure, not a hazard grade. Painting a division dark red because its SMS
 * receipts have not arrived would say the hazard there is worse than in the division next
 * to it, which is the opposite of what the number means - and it would break the one rule
 * the severity palette exists to keep.
 *
 * **A division with nothing targeted is not on the map at all.** A confirmed fraction over
 * a zero denominator is not a low number, it is no number, and shading it would report an
 * unwarned division as an unreached one. Those rows are counted under the map instead.
 *
 * The map is an addition to the table, not a replacement for it. The table carries the
 * server's worst-first order, which is the instruction - it says which division the
 * vehicle goes to first - and no arrangement of dots on a map conveys an order.
 *
 * **Placement needs division centroids the console does not have.** `GET /alerts/{id}/delivery/gaps`
 * returns codes and counts, not geometry, and `core-api` serves boundaries one division at
 * a time out of ~14,000. So the map fetches the centroids for exactly the divisions in the
 * gap list - bounded by the size of the event rather than the size of the country - and
 * says how many it could not place.
 */

import { MapShell, deliveryGapLayer, isGeoJsonSource } from '@sarana/ui';
import type { MapLike } from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef } from 'react';

import { useGNDivisionsByCode } from '../lib/queries';
import type { Gap } from '../lib/schemas';

const GAP_SOURCE = 'sarana-delivery-gaps';

/**
 * The gap rows that can be drawn, as GeoJSON.
 *
 * Exported so a test can assert the filtering and the fraction without a WebGL context.
 * `confirmed_fraction` is carried verbatim from the server rather than recomputed from
 * `confirmed / targeted`: two statements of the same figure is one that can drift, and the
 * server's is the one the summary sentence is built from.
 */
export function gapsToGeoJson(
  gaps: readonly Gap[],
  centroids: ReadonlyMap<string, readonly [number, number]>,
) {
  return {
    type: 'FeatureCollection' as const,
    features: gaps.flatMap((gap) => {
      // Nothing targeted means no fraction, not a low one.
      if (gap.targeted === 0) return [];
      const point = centroids.get(gap.gn_division_code);
      if (!point) return [];
      return [
        {
          type: 'Feature' as const,
          id: gap.gn_division_code,
          // Longitude first, as everywhere else on this platform.
          geometry: { type: 'Point' as const, coordinates: [point[0], point[1]] },
          properties: {
            gn_division_code: gap.gn_division_code,
            confirmed_fraction: gap.confirmed_fraction,
            confirmed: gap.confirmed,
            targeted: gap.targeted,
          },
        },
      ];
    }),
  };
}

export interface GapMapProps {
  readonly gaps: readonly Gap[];
  readonly className?: string;
}

export function GapMap({ gaps, className }: GapMapProps) {
  const t = useTranslations('alerts');
  const codes = useMemo(
    () => gaps.filter((gap) => gap.targeted > 0).map((gap) => gap.gn_division_code),
    [gaps],
  );
  const divisions = useGNDivisionsByCode(codes);
  const mapRef = useRef<MapLike | null>(null);

  const centroids = useMemo(() => {
    const map = new Map<string, readonly [number, number]>();
    for (const division of divisions.data ?? []) {
      if (division.centroid_lon !== null && division.centroid_lat !== null) {
        map.set(division.code, [division.centroid_lon, division.centroid_lat]);
      }
    }
    return map;
  }, [divisions.data]);

  const geojson = useMemo(() => gapsToGeoJson(gaps, centroids), [gaps, centroids]);
  const unplaceable = codes.length - geojson.features.length;

  const dataRef = useRef(geojson);
  dataRef.current = geojson;

  const onReady = useCallback((map: MapLike) => {
    mapRef.current = map;
    if (map.getSource(GAP_SOURCE)) return;
    const spec = deliveryGapLayer(GAP_SOURCE, dataRef.current);
    map.addSource(GAP_SOURCE, spec.source);
    map.addLayer(spec.layer);
  }, []);

  useEffect(() => {
    const source = mapRef.current?.getSource(GAP_SOURCE);
    if (isGeoJsonSource(source)) source.setData(geojson);
  }, [geojson]);

  if (gaps.length === 0) return null;

  return (
    <div className={className}>
      <div className="h-64">
        <MapShell
          styleUrl={process.env.NEXT_PUBLIC_SARANA_MAP_STYLE_URL ?? ''}
          label={t('gaps')}
          onReady={onReady}
          className="h-full w-full"
          fallback={
            // Every figure with its denominator, in the server's order. This is the
            // accessible equivalent of the map and it is also the more useful artefact:
            // it carries the order, which the map cannot.
            <ol className="flex flex-col gap-1">
              {gaps.map((gap) => (
                <li key={gap.gn_division_code} className="flex items-center gap-3 text-xs">
                  <span data-sarana-datum="" className="font-mono">
                    {gap.gn_division_code}
                  </span>
                  <span data-sarana-datum="" className="font-mono">
                    {gap.confirmed} / {gap.targeted}
                  </span>
                </li>
              ))}
            </ol>
          }
        />
      </div>
      <p className="mt-1 text-2xs text-[var(--text-muted)]">{t('gapMapHint')}</p>
      {unplaceable > 0 ? (
        <p role="status" className="mt-1 text-2xs text-[var(--sev-2-fg)]">
          {t('gapsUnplaceable', { count: unplaceable })}
        </p>
      ) : null}
    </div>
  );
}
