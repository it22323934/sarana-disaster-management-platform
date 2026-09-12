/**
 * The map's data transform.
 *
 * `MapShell` needs a WebGL context, so the map itself is not rendered here. What is tested
 * is everything that decides what the map *says* — which is pure, and is where a wrong
 * answer would be a wrong answer about where people are.
 */

import { describe, expect, it } from 'vitest';

import { incidentsToGeoJson, unplaceable } from './situation-map';
import type { QueueRow } from '../lib/schemas';

function row(overrides: Partial<QueueRow> = {}): QueueRow {
  return {
    id: '018f3c2a-0001-7e90-9c2d-000000000001',
    public_ref: 'INC-251128-K4M2XA',
    gn_division_code: 'LK-11-03-045',
    type: 'FLOOD',
    subtype: null,
    summary: null,
    people_at_risk: 42,
    severity: 3,
    status: 'VERIFIED',
    first_reported_at: '2025-11-27T22:18:00Z',
    location_confidence: 0.82,
    lon: 80.7718,
    lat: 7.8731,
    score: 0.71,
    model_version: 'triage-rules-1',
    factors: null,
    ...overrides,
  };
}

describe('incidentsToGeoJson', () => {
  it('puts the coordinate in GeoJSON order, longitude first', () => {
    // The commonest bug in this transform. Latitude-first would place every Sri Lankan
    // incident in the Indian Ocean off Somalia, which looks plausible enough on a
    // zoomed-out map that nobody catches it until someone is sent there.
    const [feature] = incidentsToGeoJson([row()]).features;
    expect(feature?.geometry.coordinates).toEqual([80.7718, 7.8731]);
  });

  it('omits an incident with no coordinate rather than inventing one', () => {
    // A report naming a village and nothing more is real. Placing it at the division
    // centroid would claim a precision it does not have; placing it at (0, 0) would drop
    // it in the Gulf of Guinea.
    const features = incidentsToGeoJson([row({ lon: null, lat: null })]).features;
    expect(features).toHaveLength(0);
  });

  it('omits a half-located incident, where only one of the pair is present', () => {
    expect(incidentsToGeoJson([row({ lat: null })]).features).toHaveLength(0);
    expect(incidentsToGeoJson([row({ lon: null })]).features).toHaveLength(0);
  });

  it('carries severity as a property, because the ramp is what colours the point', () => {
    // `severityColourExpression` reads `['get', 'severity']`. Nothing in this component
    // decides a colour; the design system's ramp does.
    const [feature] = incidentsToGeoJson([row({ severity: 4 })]).features;
    expect(feature?.properties.severity).toBe(4);
  });

  it('keeps the incident id as the feature id, so a click can find the row back', () => {
    const [feature] = incidentsToGeoJson([row()]).features;
    expect(feature?.id).toBe('018f3c2a-0001-7e90-9c2d-000000000001');
  });
});

describe('unplaceable', () => {
  it('counts what the map cannot show', () => {
    // Surfaced under the map, never silently dropped: an operator reading a map with
    // three points needs to know the queue has five.
    const rows = [row(), row({ id: 'b', lon: null, lat: null }), row({ id: 'c', lat: null })];
    expect(unplaceable(rows)).toBe(2);
    expect(incidentsToGeoJson(rows).features).toHaveLength(1);
  });

  it('is zero when everything is placeable', () => {
    expect(unplaceable([row(), row({ id: 'b' })])).toBe(0);
  });
});
