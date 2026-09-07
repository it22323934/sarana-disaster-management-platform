'use client';

/**
 * Selecting an area by drawing on the map.
 *
 * The last of the four selection modes build file 20 asks for: "on the map by GN division,
 * DS division, district, **or a drawn polygon that snaps to division boundaries**".
 *
 * **It snaps by selecting whole divisions, never parts of one.** That is what snapping
 * means for an alert: the household directory is keyed by GN division, so there is no such
 * thing as warning half of one. The shape decides which divisions are in; it never becomes
 * the target area itself.
 *
 * **One request, then local geometry.** The drawn shape's bounding box goes to
 * `GET /admin/gn-divisions?bbox=…`, which returns every division in the box with its
 * centroid. The polygon test then runs here. The alternative — asking the server which
 * divisions *intersect* an arbitrary polygon — has no endpoint, and building one on top of
 * geometry served a division at a time out of ~14,000 would be thousands of requests during
 * the minutes this service is busiest.
 *
 * **The centroid rule is stated on screen.** A division is selected when its centre lies
 * inside the shape, so one lying half inside is out. An operator drawing along a river has
 * to know that, because the alternative reading — anything the shape touches — differs by
 * exactly the divisions on the boundary, which are the ones being decided about.
 *
 * **Nothing is applied until the operator presses apply.** Drawing shows a count; it does
 * not change the selection. A shape that silently replaced a carefully typed list of codes
 * on the first stray click would be worse than no drawing tool at all.
 */

import { Button, MapShell, drawAreaLayer, drawVertexLayer, isGeoJsonSource } from '@sarana/ui';
import type { MapLike, MapMouseEventLike } from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { gatewayFetch } from '../lib/gateway-client';
import {
  bboxParam,
  divisionsInPolygon,
  serverBoundingBox,
  type Position,
} from '../lib/geometry';
import { gnDivisionListSchema, type GNDivisionRow } from '../lib/schemas';
import { ErrorPanel } from './degraded';

const AREA_SOURCE = 'sarana-draw-area';
const VERTEX_SOURCE = 'sarana-draw-vertices';

/** Below this a shape encloses no area, so it can select nothing. */
const MINIMUM_VERTICES = 3;

/**
 * The most divisions one drawn shape may select.
 *
 * A box drawn around the whole country returns thousands of rows, and an alert addressed to
 * thousands of divisions is a national fan-out somebody made with a mouse gesture. The cap
 * is on the *response* rather than on the shape, so a large but sparse area is fine and a
 * small dense one is what gets caught — which is the right way round. Above it the screen
 * refuses and says to draw a smaller area, rather than truncating and selecting a subset
 * nobody chose.
 */
const MAX_DIVISIONS_PER_SHAPE = 400;

interface Found {
  readonly divisions: readonly GNDivisionRow[];
  readonly withoutCentroid: number;
  readonly truncated: boolean;
}

export interface AreaDrawProps {
  /** Called with the codes inside the shape, only when the operator applies them. */
  readonly onApply: (codes: string[]) => void;
  readonly className?: string;
}

export function AreaDraw({ onApply, className }: AreaDrawProps) {
  const t = useTranslations('compose');

  const [vertices, setVertices] = useState<Position[]>([]);
  const [found, setFound] = useState<Found | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const mapRef = useRef<MapLike | null>(null);

  const polygon = useMemo(
    () => ({
      type: 'FeatureCollection' as const,
      features:
        vertices.length >= MINIMUM_VERTICES
          ? [
              {
                type: 'Feature' as const,
                geometry: {
                  type: 'Polygon' as const,
                  // GeoJSON requires the ring closed. The operator has not repeated the
                  // first vertex, so it is repeated here for rendering only - the point-in
                  // -polygon test closes the ring itself and does not need this.
                  coordinates: [[...vertices, vertices[0] as Position]],
                },
                properties: {},
              },
            ]
          : [],
    }),
    [vertices],
  );

  const vertexPoints = useMemo(
    () => ({
      type: 'FeatureCollection' as const,
      features: vertices.map((position, index) => ({
        type: 'Feature' as const,
        id: index,
        geometry: { type: 'Point' as const, coordinates: [position[0], position[1]] },
        properties: {},
      })),
    }),
    [vertices],
  );

  const dataRef = useRef({ polygon, vertexPoints });
  dataRef.current = { polygon, vertexPoints };

  const onReady = useCallback((map: MapLike) => {
    mapRef.current = map;
    if (!map.getSource(AREA_SOURCE)) {
      const spec = drawAreaLayer(AREA_SOURCE, dataRef.current.polygon);
      map.addSource(AREA_SOURCE, spec.source);
      map.addLayer(spec.layer);
    }
    if (!map.getSource(VERTEX_SOURCE)) {
      const spec = drawVertexLayer(VERTEX_SOURCE, dataRef.current.vertexPoints);
      map.addSource(VERTEX_SOURCE, spec.source);
      map.addLayer(spec.layer);
    }
    // A crosshair, so the map reads as a drawing surface rather than a picture. Without it
    // the first click feels like it did nothing.
    const canvas = map.getCanvas?.();
    if (canvas) canvas.style.cursor = 'crosshair';

    map.on('click', (event: MapMouseEventLike) => {
      // Appended through the setter rather than from a captured array: this handler is
      // registered once for the life of the map, so a closed-over `vertices` would be the
      // empty one forever and every click would replace the first vertex.
      setVertices((current) => [...current, [event.lngLat.lng, event.lngLat.lat]]);
      // Any earlier result described a different shape.
      setFound(null);
    });
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const area = map.getSource(AREA_SOURCE);
    if (isGeoJsonSource(area)) area.setData(polygon);
    const points = map.getSource(VERTEX_SOURCE);
    if (isGeoJsonSource(points)) points.setData(vertexPoints);
  }, [polygon, vertexPoints]);

  const closeable = vertices.length >= MINIMUM_VERTICES;

  async function search(): Promise<void> {
    const box = serverBoundingBox(vertices);
    if (box === null) return;

    setBusy(true);
    setFailure(null);
    setFound(null);
    try {
      const rows = await gatewayFetch('admin/gn-divisions', {
        query: {
          bbox: bboxParam(box),
          // One over the cap, so a response at the cap can be told from one above it.
          limit: MAX_DIVISIONS_PER_SHAPE + 1,
        },
        schema: gnDivisionListSchema,
      });

      const { selected, withoutCentroid } = divisionsInPolygon(rows, vertices);
      setFound({
        divisions: selected,
        withoutCentroid,
        truncated: selected.length > MAX_DIVISIONS_PER_SHAPE,
      });
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  function reset(): void {
    setVertices([]);
    setFound(null);
    setFailure(null);
  }

  return (
    <section className={className}>
      <p className="text-xs text-[var(--text-muted)]">{t('drawHint')}</p>

      <div className="mt-2 h-72">
        <MapShell
          styleUrl={process.env.NEXT_PUBLIC_SARANA_MAP_STYLE_URL ?? ''}
          label={t('drawMap')}
          onReady={onReady}
          className="h-full w-full"
          fallback={
            // A map is the only way to draw on a map. Rather than pretend otherwise, the
            // fallback says so and points at the three modes that need no map at all -
            // which is also the answer for a screen reader user, for whom a freehand shape
            // is not an input method.
            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-medium">{t('drawMap')}</h3>
              <p className="text-xs">{t('drawUnavailable')}</p>
            </div>
          }
        />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <span className="text-2xs text-[var(--text-muted)]">
          {t('drawVertices', { count: vertices.length })}
        </span>
        <Button
          variant="secondary"
          size="sm"
          disabled={!closeable || busy}
          busy={busy}
          busyLabel={t('drawSearch')}
          onClick={search}
        >
          {t('drawSearch')}
        </Button>
        <Button variant="ghost" size="sm" disabled={vertices.length === 0} onClick={reset}>
          {t('drawClear')}
        </Button>
        {!closeable && vertices.length > 0 ? (
          <span className="text-2xs text-[var(--pending)]">{t('drawNeedsThree')}</span>
        ) : null}
      </div>

      {failure ? <ErrorPanel error={failure} className="mt-2" /> : null}

      {found ? (
        <div className="mt-3 flex flex-col gap-2 rounded-[var(--radius-default)] border border-[var(--divider)] p-3">
          {found.truncated ? (
            // Refused rather than truncated. Selecting the first 400 of a larger set is
            // selecting a subset nobody chose, on the screen that decides who gets warned.
            <p role="alert" className="text-xs text-[var(--sev-3-fg)]">
              {t('drawTooMany', { count: found.divisions.length, cap: MAX_DIVISIONS_PER_SHAPE })}
            </p>
          ) : (
            <>
              <p className="text-sm">
                {t('drawFound', { count: found.divisions.length })}
              </p>
              {/* The rule, beside the count it produced. A division lying half inside the
                  shape is out, and the divisions on the boundary are exactly the ones an
                  operator is deciding about. */}
              <p className="text-2xs text-[var(--text-muted)]">{t('drawCentroidRule')}</p>
              {found.withoutCentroid > 0 ? (
                <p className="text-2xs text-[var(--sev-2-fg)]">
                  {t('drawWithoutCentroid', { count: found.withoutCentroid })}
                </p>
              ) : null}
              <Button
                variant="primary"
                size="sm"
                className="self-start"
                disabled={found.divisions.length === 0}
                onClick={() => onApply(found.divisions.map((division) => division.code))}
              >
                {t('drawApply', { count: found.divisions.length })}
              </Button>
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}
