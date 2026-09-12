/**
 * The map layer builders.
 *
 * `MapShell` itself needs a WebGL context and a tile server, so it is not rendered here.
 * What is tested is everything that decides what the map *says* - which is all pure, and
 * is where a wrong answer would be a wrong answer about a hazard rather than a rendering
 * glitch.
 */

import { describe, expect, it } from 'vitest';

import { SEVERITY, SEVERITY_LEVELS } from '../tokens/severity.js';
import { gnDivisionLayer, heatLayer, incidentLayer, severityColourExpression } from './map-shell.js';

describe('severityColourExpression', () => {
  it('maps every level to its own ramp colour', () => {
    const expression = severityColourExpression();
    for (const level of SEVERITY_LEVELS) {
      const index = expression.indexOf(level);
      expect(index, `sev-${level} is missing from the match expression`).toBeGreaterThan(0);
      expect(expression[index + 1]).toBe(SEVERITY[level].base);
    }
  });

  it('falls back to the informational colour, not to the severe one', () => {
    // MapLibre requires a fallback on `match`. A feature with no severity property is
    // unclassified, and painting it deep red would invent a warning that nobody issued.
    const expression = severityColourExpression();
    expect(expression[expression.length - 1]).toBe(SEVERITY[0].base);
  });

  it('reads the severity from the feature rather than from a style constant', () => {
    expect(severityColourExpression()[1]).toEqual(['get', 'severity']);
  });
});

describe('the layers', () => {
  it('outlines divisions in the divider colour, not in the severity colour', () => {
    // At national zoom, fourteen thousand severity-coloured outlines merge into a wash
    // that reads as one large severe area.
    const spec = gnDivisionLayer('divisions', { type: 'FeatureCollection', features: [] });
    const paint = spec.layer.paint as Record<string, unknown>;
    expect(paint['fill-outline-color']).toBe('#2A3548');
  });

  it('grows incident markers with zoom so they stay hittable at national scale', () => {
    const spec = incidentLayer('incidents', { type: 'FeatureCollection', features: [] });
    const paint = spec.layer.paint as Record<string, unknown>;
    expect(paint['circle-radius']).toEqual([
      'interpolate',
      ['linear'],
      ['zoom'],
      7,
      4,
      12,
      10,
    ]);
  });

  it('weights the heatmap by report count, not by severity', () => {
    // This layer answers "where are people reporting from", which is a coverage
    // question. Weighting it by severity would let one class-4 report light up a
    // division nobody else has reported from.
    const spec = heatLayer('reports', { type: 'FeatureCollection', features: [] });
    const paint = spec.layer.paint as Record<string, unknown>;
    expect(JSON.stringify(paint['heatmap-weight'])).toContain('reports');
    expect(JSON.stringify(paint['heatmap-weight'])).not.toContain('severity');
  });

  it('keeps the heatmap ramp cool, so density never reads as severity', () => {
    const spec = heatLayer('reports', { type: 'FeatureCollection', features: [] });
    const paint = spec.layer.paint as Record<string, unknown>;
    const ramp = JSON.stringify(paint['heatmap-color']);
    for (const level of SEVERITY_LEVELS) {
      expect(ramp).not.toContain(SEVERITY[level].base);
    }
  });

  it('names its layer after its source, so two maps on a page cannot collide', () => {
    expect(gnDivisionLayer('a', {}).id).toBe('a-fill');
    expect(incidentLayer('b', {}).id).toBe('b-points');
    expect(heatLayer('c', {}).id).toBe('c-heat');
  });
});
