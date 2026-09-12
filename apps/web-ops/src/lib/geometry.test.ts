/**
 * The geometry behind drawing an area, and the ways it goes quietly wrong.
 *
 * This code decides which divisions an alert is addressed to. Every failure here is silent:
 * a polygon test that is subtly wrong selects the wrong divisions, and the alert goes to the
 * wrong district while the screen looks entirely correct. So the tests are written around
 * the specific ways ray casting is got wrong rather than around a happy path.
 */

import { describe, expect, it } from 'vitest';

import {
  bboxParam,
  boundingBox,
  divisionsInPolygon,
  pointInPolygon,
  serverBoundingBox,
  type Position,
} from './geometry';

/** A square over Kandy, roughly. Longitude first, as everywhere on this platform. */
const SQUARE: readonly Position[] = [
  [80.5, 7.2],
  [80.9, 7.2],
  [80.9, 7.4],
  [80.5, 7.4],
];

/** A concave shape: the notch is what separates a real test from a bounding-box test. */
const L_SHAPE: readonly Position[] = [
  [0, 0],
  [4, 0],
  [4, 2],
  [2, 2],
  [2, 4],
  [0, 4],
];

describe('a point against a polygon', () => {
  it('is inside when it is inside', () => {
    expect(pointInPolygon([80.7, 7.3], SQUARE)).toBe(true);
  });

  it('is outside when it is outside', () => {
    expect(pointInPolygon([81.5, 7.3], SQUARE)).toBe(false);
    expect(pointInPolygon([80.7, 8.9], SQUARE)).toBe(false);
  });

  it('respects a concave notch rather than testing the bounding box', () => {
    // (3, 3) is inside the L's bounding box and outside the L. A bounding-box test passes
    // every other case in this file and fails this one, which is why it is here.
    expect(pointInPolygon([1, 1], L_SHAPE)).toBe(true);
    expect(pointInPolygon([3, 1], L_SHAPE)).toBe(true);
    expect(pointInPolygon([1, 3], L_SHAPE)).toBe(true);
    expect(pointInPolygon([3, 3], L_SHAPE)).toBe(false);
  });

  it('counts an edge once when the ray passes through a shared vertex', () => {
    // The classic ray-casting bug. A `>=` comparison counts both edges meeting at a vertex
    // the ray passes through, which flips the answer for every point beyond it. This
    // diamond puts a vertex at exactly the test latitude.
    const diamond: readonly Position[] = [
      [0, 1],
      [1, 2],
      [2, 1],
      [1, 0],
    ];
    expect(pointInPolygon([1, 1], diamond)).toBe(true);
    expect(pointInPolygon([3, 1], diamond)).toBe(false);
    expect(pointInPolygon([-1, 1], diamond)).toBe(false);
  });

  it('treats the shape as closed without the caller repeating the first vertex', () => {
    // An operator finishing a shape by pressing a button has not repeated anything, so the
    // closing edge has to be implied. Explicitly closing it must not change the answer.
    const closed: readonly Position[] = [...SQUARE, SQUARE[0] as Position];
    for (const point of [
      [80.7, 7.3],
      [80.51, 7.21],
      [81.5, 7.3],
    ] as Position[]) {
      expect(pointInPolygon(point, closed)).toBe(pointInPolygon(point, SQUARE));
    }
  });

  it('contains nothing when the shape encloses no area', () => {
    // Two clicks is a line and one is a point. Returning false selects nothing, which is
    // the safe direction: the dangerous bug here is selecting everything.
    expect(pointInPolygon([1, 1], [])).toBe(false);
    expect(pointInPolygon([1, 1], [[0, 0]])).toBe(false);
    expect(
      pointInPolygon(
        [1, 1],
        [
          [0, 0],
          [2, 2],
        ],
      ),
    ).toBe(false);
  });

  it('gives the same answer whichever way the shape was drawn', () => {
    // Clockwise and anticlockwise are the same area. An operator does not know which way
    // they went round, and the result must not depend on it.
    const reversed = [...SQUARE].reverse();
    expect(pointInPolygon([80.7, 7.3], reversed)).toBe(true);
    expect(pointInPolygon([81.5, 7.3], reversed)).toBe(false);
  });
});

describe('the bounding box sent to the server', () => {
  it('covers every vertex', () => {
    expect(boundingBox(SQUARE)).toEqual([80.5, 7.2, 80.9, 7.4]);
  });

  it('is null for an empty shape rather than an infinite box', () => {
    // `Math.min` of nothing is Infinity, and a box of infinities would ask core-api for
    // the whole world and be refused for the wrong reason.
    expect(boundingBox([])).toBeNull();
    expect(serverBoundingBox([])).toBeNull();
  });

  it('is never degenerate, because the server refuses a zero-width box', () => {
    // `_parse_bbox` requires each minimum to be strictly less than its maximum. A shape
    // drawn as a straight line along a road would otherwise be a validation error rather
    // than a selection of nothing.
    const line: readonly Position[] = [
      [80.5, 7.2],
      [80.5, 7.4],
    ];
    const box = serverBoundingBox(line);
    expect(box).not.toBeNull();
    const [minLon, minLat, maxLon, maxLat] = box as [number, number, number, number];
    expect(maxLon).toBeGreaterThan(minLon);
    expect(maxLat).toBeGreaterThan(minLat);
  });

  it('is formatted in the order core-api parses', () => {
    // min_lon,min_lat,max_lon,max_lat. Any other order is a box somewhere else, and the
    // server will either refuse it or - worse - accept a valid box over the wrong area.
    expect(bboxParam([80.5, 7.2, 80.9, 7.4])).toBe('80.500000,7.200000,80.900000,7.400000');
  });
});

describe('selecting divisions', () => {
  const divisions = [
    { code: 'LK-11-03-045', centroid_lon: 80.7, centroid_lat: 7.3 },
    { code: 'LK-11-03-046', centroid_lon: 81.5, centroid_lat: 7.3 },
    { code: 'LK-11-03-047', centroid_lon: null, centroid_lat: null },
  ];

  it('takes the divisions whose centroid is inside', () => {
    const { selected } = divisionsInPolygon(divisions, SQUARE);
    expect(selected.map((division) => division.code)).toEqual(['LK-11-03-045']);
  });

  it('counts the divisions it could not place rather than dropping them silently', () => {
    // A division with no centroid is not selected, and the screen has to say how many.
    // Otherwise an operator draws over an area and warns fewer people than they saw.
    const { withoutCentroid } = divisionsInPolygon(divisions, SQUARE);
    expect(withoutCentroid).toBe(1);
  });

  it('selects nothing from a shape that encloses nothing', () => {
    expect(divisionsInPolygon(divisions, []).selected).toEqual([]);
  });
});
