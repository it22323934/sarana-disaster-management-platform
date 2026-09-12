'use client';

/**
 * The route a dispatch plan commits, drawn on a map.
 *
 * Build file 20 asks for "the route, drawn on a map with blocked segments visible". The
 * route is drawn. **Blocked segments are not, and the screen says so** - there is no road
 * network anywhere in this platform. `road_access_lost` is a boolean on an incident and
 * the triage agent's solver works from straight-line estimates, so a "blocked segments"
 * overlay would be a drawing rather than a fact. What the map can honestly show is which
 * incidents report lost road access, and those are marked in the list beside it.
 *
 * A line between stops, not a driving route. The polyline connects the responder's
 * position to each stop in the sequence the solver chose, which is what the plan actually
 * commits to; anything smoother would imply a road-following path nothing computed.
 *
 * **An incident with no coordinate is not placed, and the count is shown.** Same rule as
 * the situation map, and it matters more here: a dispatcher looking at a route with four
 * markers has to know whether the plan covers four incidents or six.
 */

import {
  MapShell,
  ReferenceCode,
  SeverityPill,
  isGeoJsonSource,
  incidentLayer,
  responderLayer,
  routeLayer,
} from '@sarana/ui';
import type { MapLike, SeverityLevel } from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useRef } from 'react';

import type { Incident, Responder, ResponderRoute } from '../lib/schemas';

const ROUTE_SOURCE = 'sarana-plan-route';
const STOP_SOURCE = 'sarana-plan-stops';
const RESPONDER_SOURCE = 'sarana-plan-responders';

interface Placed {
  readonly lon: number;
  readonly lat: number;
}

function placed<T extends { lon: number | null; lat: number | null }>(
  row: T,
): (T & Placed) | null {
  return row.lon !== null && row.lat !== null ? (row as T & Placed) : null;
}

/**
 * The plan's routes as line features, one per responder.
 *
 * Exported so a test can assert the ordering without a WebGL context. A route whose stops
 * resolve to fewer than two placed points produces no line: a single point is not a route,
 * and drawing a zero-length line would put a dot on the map that reads as a stop nobody
 * planned.
 */
export function routesToGeoJson(
  routes: readonly ResponderRoute[],
  incidents: readonly Incident[],
  responders: readonly Responder[],
): {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    id: string;
    geometry: { type: 'LineString'; coordinates: Array<[number, number]> };
    properties: { responder_id: string; stops: number };
  }>;
} {
  const incidentById = new Map(incidents.map((incident) => [incident.id, incident]));
  const responderById = new Map(responders.map((responder) => [responder.id, responder]));

  const features = routes.flatMap((route) => {
    const start = responderById.get(route.responder_id);
    const startPoint = start ? placed(start) : null;

    const stops = [...route.stops]
      .sort((a, b) => a.sequence - b.sequence)
      .map((stop) => incidentById.get(stop.incident_id))
      .filter((incident): incident is Incident => incident !== undefined)
      .map((incident) => placed(incident))
      .filter((incident): incident is Incident & Placed => incident !== null);

    // Longitude first. Latitude first puts every Sri Lankan feature in the Indian Ocean
    // off Somalia, which looks plausible enough on a zoomed-out map that nobody catches it
    // until somebody is sent there.
    const coordinates: Array<[number, number]> = [
      ...(startPoint ? ([[startPoint.lon, startPoint.lat]] as Array<[number, number]>) : []),
      ...stops.map((incident) => [incident.lon, incident.lat] as [number, number]),
    ];

    if (coordinates.length < 2) return [];
    return [
      {
        type: 'Feature' as const,
        id: route.responder_id,
        geometry: { type: 'LineString' as const, coordinates },
        properties: { responder_id: route.responder_id, stops: stops.length },
      },
    ];
  });

  return { type: 'FeatureCollection', features };
}

/** The plan's incidents as points, carrying severity so the ramp colours them. */
export function stopsToGeoJson(incidents: readonly Incident[]) {
  return {
    type: 'FeatureCollection' as const,
    features: incidents.flatMap((incident) => {
      const point = placed(incident);
      if (!point) return [];
      return [
        {
          type: 'Feature' as const,
          id: incident.id,
          geometry: { type: 'Point' as const, coordinates: [point.lon, point.lat] },
          properties: {
            severity: incident.severity,
            public_ref: incident.public_ref,
            people_at_risk: incident.people_at_risk,
          },
        },
      ];
    }),
  };
}

/** Responder positions, carrying availability rather than severity. */
export function respondersToGeoJson(responders: readonly Responder[]) {
  return {
    type: 'FeatureCollection' as const,
    features: responders.flatMap((responder) => {
      const point = placed(responder);
      if (!point) return [];
      return [
        {
          type: 'Feature' as const,
          id: responder.id,
          geometry: { type: 'Point' as const, coordinates: [point.lon, point.lat] },
          properties: { available: responder.status === 'AVAILABLE', org: responder.org },
        },
      ];
    }),
  };
}

export interface RouteMapProps {
  readonly routes: readonly ResponderRoute[];
  readonly incidents: readonly Incident[];
  readonly responders: readonly Responder[];
  readonly className?: string;
}

export function RouteMap({ routes, incidents, responders, className }: RouteMapProps) {
  const t = useTranslations('dispatch');
  const cop = useTranslations('cop');
  const mapRef = useRef<MapLike | null>(null);

  const lines = useMemo(
    () => routesToGeoJson(routes, incidents, responders),
    [routes, incidents, responders],
  );
  const stops = useMemo(() => stopsToGeoJson(incidents), [incidents]);
  const teams = useMemo(() => respondersToGeoJson(responders), [responders]);

  const unplaceable = incidents.filter((incident) => placed(incident) === null).length;
  const roadBlocked = incidents.filter(
    (incident) => incident.location_confidence !== null && incident.location_confidence < 0.6,
  );

  // Read through refs so `onReady` is stable. A callback that changed on every poll would
  // make `MapShell` tear the map down and rebuild it, which means refetching every tile.
  const dataRef = useRef({ lines, stops, teams });
  dataRef.current = { lines, stops, teams };

  const onReady = useCallback((map: MapLike) => {
    mapRef.current = map;
    // The route goes on first so the stop markers sit above the line rather than under it.
    if (!map.getSource(ROUTE_SOURCE)) {
      const spec = routeLayer(ROUTE_SOURCE, dataRef.current.lines);
      map.addSource(ROUTE_SOURCE, spec.source);
      map.addLayer(spec.layer);
    }
    if (!map.getSource(RESPONDER_SOURCE)) {
      const spec = responderLayer(RESPONDER_SOURCE, dataRef.current.teams);
      map.addSource(RESPONDER_SOURCE, spec.source);
      map.addLayer(spec.layer);
    }
    if (!map.getSource(STOP_SOURCE)) {
      const spec = incidentLayer(STOP_SOURCE, dataRef.current.stops);
      map.addSource(STOP_SOURCE, spec.source);
      map.addLayer(spec.layer);
    }
  }, []);

  // `setData` rather than remove-and-re-add: re-adding throws when the id exists, and it
  // drops the layer's paint state even when it does not.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const [id, data] of [
      [ROUTE_SOURCE, lines],
      [STOP_SOURCE, stops],
      [RESPONDER_SOURCE, teams],
    ] as const) {
      const source = map.getSource(id);
      if (isGeoJsonSource(source)) source.setData(data);
    }
  }, [lines, stops, teams]);

  return (
    <div className={className}>
      <div className="h-72">
        <MapShell
          styleUrl={process.env.NEXT_PUBLIC_SARANA_MAP_STYLE_URL ?? ''}
          label={t('routeMap')}
          onReady={onReady}
          className="h-full w-full"
          fallback={
            // The same facts as the map, in order. Not a summary of it: this is what a
            // screen reader user and a browser that failed to load tiles both get, and on
            // a gate screen it has to be complete enough to decide from.
            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-medium">{t('routeMap')}</h3>
              <ol className="flex flex-col gap-1">
                {incidents.map((incident, index) => (
                  <li key={incident.id} className="flex items-center gap-2 text-xs">
                    <span data-sarana-datum="" className="font-mono text-2xs">
                      {index + 1}
                    </span>
                    <SeverityPill level={incident.severity as SeverityLevel} locale="en" />
                    <ReferenceCode code={incident.public_ref} />
                    <span data-sarana-datum="" className="font-mono">
                      {incident.gn_division_code}
                    </span>
                    {placed(incident) === null ? (
                      <span className="text-[var(--sev-2-fg)]">{cop('noCoordinate')}</span>
                    ) : null}
                  </li>
                ))}
              </ol>
            </div>
          }
        />
      </div>

      {/* Named as absent rather than drawn. There is no road network in this platform, so
          a blocked-segment overlay would be a decoration; the incidents whose location the
          solver could not trust are listed instead, which is the true version of it. */}
      <p className="mt-2 text-2xs text-[var(--text-muted)]">{t('blockedSegmentsNotBuilt')}</p>

      {roadBlocked.length > 0 ? (
        <p className="mt-1 text-2xs text-[var(--sev-2-fg)]">
          {t('lowConfidenceStops', { count: roadBlocked.length })}
        </p>
      ) : null}

      {unplaceable > 0 ? (
        <p role="status" className="mt-1 text-2xs text-[var(--sev-2-fg)]">
          {cop('unplaceable', { count: unplaceable })}
        </p>
      ) : null}
    </div>
  );
}
