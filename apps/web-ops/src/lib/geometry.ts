/**
 * The geometry behind selecting an area by drawing on the map.
 *
 * Pure functions with no map library in them, so the part that decides which divisions an
 * operator selected is testable without a WebGL context. The failure this guards against is
 * quiet: a polygon test that is subtly wrong selects the wrong divisions, and an alert goes
 * to the wrong district while looking entirely correct on screen.
 *
 * **A drawn shape selects whole divisions, never parts of one.** That is what "snaps to
 * division boundaries" means here, and it is not a simplification: an alert is addressed to
 * GN divisions because that is the unit the household directory is keyed by. There is no
 * such thing as warning half a division.
 *
 * **The test is on the division's centroid.** The alternative — any division whose boundary
 * intersects the drawn shape — needs every candidate boundary, and `core-api` serves
 * geometry one division at a time out of roughly 14,000. Centroid containment needs only
 * the centroids, which arrive with the division list in a single bbox query. The rule is
 * stated on screen, because an operator drawing along a river needs to know whether a
 * division lying half inside is in or out.
 *
 * Coordinates are `[longitude, latitude]` throughout, matching GeoJSON and every other
 * coordinate in this platform. Latitude-first puts Sri Lanka in the Indian Ocean off
 * Somalia, which looks plausible on a zoomed-out map until somebody is sent there.
 */

/** `[longitude, latitude]`, in that order, always. */
export type Position = readonly [number, number];

/** `[minLon, minLat, maxLon, maxLat]`, the order `core-api` parses. */
export type BoundingBox = readonly [number, number, number, number];

/**
 * The smallest box containing every vertex.
 *
 * This is what goes to the server: one request for the divisions in the box, then the
 * polygon test locally. The box is always at least as large as the polygon, so nothing
 * inside the drawn shape can be missed by the query that feeds the test.
 */
export function boundingBox(polygon: readonly Position[]): BoundingBox | null {
  if (polygon.length === 0) return null;
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  for (const [lon, lat] of polygon) {
    if (lon < minLon) minLon = lon;
    if (lat < minLat) minLat = lat;
    if (lon > maxLon) maxLon = lon;
    if (lat > maxLat) maxLat = lat;
  }
  return [minLon, minLat, maxLon, maxLat];
}

/**
 * The smallest area `core-api` will accept as a box.
 *
 * Its `_parse_bbox` refuses a box whose minimum is not strictly less than its maximum, so a
 * shape drawn as a straight line — three clicks along a road, say — would be rejected with a
 * validation error rather than simply selecting nothing. Nudging a degenerate box by this
 * much keeps the request valid and changes no answer: the polygon test still decides, and a
 * zero-area polygon contains no centroid.
 *
 * Roughly a metre at this latitude. Small enough to be meaningless, large enough that
 * floating point cannot collapse it again.
 */
const MINIMUM_SPAN_DEGREES = 1e-5;

/** A bbox the server will accept, widened only if the drawn shape was degenerate. */
export function serverBoundingBox(polygon: readonly Position[]): BoundingBox | null {
  const box = boundingBox(polygon);
  if (box === null) return null;
  const [minLon, minLat, maxLon, maxLat] = box;
  return [
    minLon,
    minLat,
    maxLon - minLon < MINIMUM_SPAN_DEGREES ? minLon + MINIMUM_SPAN_DEGREES : maxLon,
    maxLat - minLat < MINIMUM_SPAN_DEGREES ? minLat + MINIMUM_SPAN_DEGREES : maxLat,
  ];
}

/** The query-string form `core-api` parses: `min_lon,min_lat,max_lon,max_lat`. */
export function bboxParam(box: BoundingBox): string {
  return box.map((value) => value.toFixed(6)).join(',');
}

/**
 * Whether a point lies inside a polygon.
 *
 * Ray casting with the even-odd rule: count how many edges a ray from the point crosses.
 * The polygon is treated as closed whether or not the caller repeated the first vertex,
 * because an operator finishing a shape by pressing a button has not repeated anything.
 *
 * The `(a[1] > lat) !== (b[1] > lat)` test is the standard one and it is written this way
 * deliberately: it counts an edge exactly once when the ray passes a shared vertex, which
 * the more obvious `>=` formulation does twice — and a double count inverts the answer for
 * every point beyond it. On a division sitting on the boundary of a drawn shape that is the
 * difference between warning a district and not.
 *
 * Degenerate shapes contain nothing: fewer than three vertices is a point or a line, and
 * neither encloses area. Returning false is the safe answer — it selects nothing rather than
 * selecting everything.
 */
export function pointInPolygon(point: Position, polygon: readonly Position[]): boolean {
  if (polygon.length < 3) return false;

  const [lon, lat] = point;
  let inside = false;

  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const a = polygon[i];
    const b = polygon[j];
    if (!a || !b) continue;

    const straddles = a[1] > lat !== b[1] > lat;
    if (!straddles) continue;

    // Longitude of the edge where it crosses this latitude.
    const crossingLon = ((b[0] - a[0]) * (lat - a[1])) / (b[1] - a[1]) + a[0];
    if (lon < crossingLon) inside = !inside;
  }

  return inside;
}

/** Anything with a centroid the polygon test can be run against. */
export interface HasCentroid {
  readonly code: string;
  readonly centroid_lon: number | null;
  readonly centroid_lat: number | null;
}

/**
 * The divisions whose centroid falls inside the drawn shape.
 *
 * A division with no centroid is **not** selected, and the caller is expected to say how
 * many were skipped. Seed boundaries below district level are generated rectangles and a
 * division loaded without geometry has no centroid at all; silently dropping those would
 * mean an operator drew over an area and warned fewer people than they saw.
 */
export function divisionsInPolygon<T extends HasCentroid>(
  divisions: readonly T[],
  polygon: readonly Position[],
): { readonly selected: T[]; readonly withoutCentroid: number } {
  const selected: T[] = [];
  let withoutCentroid = 0;

  for (const division of divisions) {
    if (division.centroid_lon === null || division.centroid_lat === null) {
      withoutCentroid += 1;
      continue;
    }
    if (pointInPolygon([division.centroid_lon, division.centroid_lat], polygon)) {
      selected.push(division);
    }
  }

  return { selected, withoutCentroid };
}
