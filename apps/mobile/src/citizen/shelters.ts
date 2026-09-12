/**
 * The nearest open shelter, from cache.
 *
 * On the home screen and therefore on the emergency path, which sets the constraint: it
 * has to answer with no network, because the moment somebody needs a shelter is the
 * moment the cell tower is congested. Everything here reads a cached list and does
 * arithmetic.
 *
 * Distance is straight-line. Saying so is the point: a shelter 900m away across a flooded
 * river is not 900m away, and the UI shows the figure as "about 900m" with a directions
 * link rather than as a walk time it cannot compute. The same honesty the triage agent's
 * routing has about not having a road network.
 */

export interface Shelter {
  readonly id: string;
  readonly name_si: string;
  readonly name_ta: string;
  readonly name_en: string;
  readonly gn_division_code: string;
  readonly latitude: number;
  readonly longitude: number;
  readonly capacity: number;
  readonly occupancy: number;
  /** OPEN, FULL or CLOSED, as the shelter register reports it. */
  readonly status: string;
  /** When this row was cached. Shown, because a stale shelter list is dangerous. */
  readonly cached_at: string;
}

export interface NearbyShelter {
  readonly shelter: Shelter;
  /** Straight-line metres. Never presented as a distance to walk. */
  readonly metres: number;
  readonly hasSpace: boolean;
}

/** Mean Earth radius, in metres. */
const EARTH_RADIUS_M = 6_371_008.8;

/**
 * Great-circle distance between two points.
 *
 * Haversine rather than an equirectangular approximation: the approximation is faster and
 * wrong by a few percent, and a few percent of 900m is not worth the arithmetic saved on a
 * list of forty shelters.
 */
export function distanceMetres(
  from: { latitude: number; longitude: number },
  to: { latitude: number; longitude: number },
): number {
  const toRadians = (degrees: number) => (degrees * Math.PI) / 180;
  const dLat = toRadians(to.latitude - from.latitude);
  const dLon = toRadians(to.longitude - from.longitude);
  const lat1 = toRadians(from.latitude);
  const lat2 = toRadians(to.latitude);

  const a =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return Math.round(2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a))));
}

/**
 * The nearest shelters that will take someone.
 *
 * **A full shelter is listed, not hidden.** Sending a family to a shelter that turns them
 * away is worse than telling them it is full and showing them the next one, and hiding it
 * would leave a household walking past the building they were told to go to. `hasSpace`
 * carries the difference and the UI shows both.
 *
 * A CLOSED shelter is excluded: it is not a place to go, and listing it would be noise on
 * a screen someone is reading in a hurry.
 */
export function nearestShelters(
  shelters: readonly Shelter[],
  from: { latitude: number; longitude: number } | null,
  { limit = 3 }: { limit?: number } = {},
): NearbyShelter[] {
  const open = shelters.filter((shelter) => shelter.status !== 'CLOSED');

  if (from === null) {
    // No location. Ordering by distance is impossible, so they are ordered by space -
    // which is the next most useful thing and is honest about why.
    return open
      .slice()
      .sort((a, b) => b.capacity - b.occupancy - (a.capacity - a.occupancy))
      .slice(0, limit)
      .map((shelter) => ({
        shelter,
        metres: -1,
        hasSpace: shelter.occupancy < shelter.capacity,
      }));
  }

  return open
    .map((shelter) => ({
      shelter,
      metres: distanceMetres(from, shelter),
      hasSpace: shelter.occupancy < shelter.capacity,
    }))
    // Space first among shelters at a similar distance is tempting and wrong: someone in
    // water wants the nearest roof, and the list shows them whether it has room.
    .sort((a, b) => a.metres - b.metres)
    .slice(0, limit);
}

/**
 * How old the cached list is, and whether to say so.
 *
 * Six hours. A shelter that opened this morning is not in a list cached last night, and a
 * household that walks to a building that is not open yet has spent the walk. The screen
 * says how old the figures are rather than implying they are live.
 */
export const SHELTER_CACHE_WARN_MS = 6 * 60 * 60 * 1000;

export function shelterCacheAge(
  shelters: readonly Shelter[],
  now: number,
): { ageMs: number; stale: boolean } | null {
  if (shelters.length === 0) return null;
  const newest = Math.max(...shelters.map((shelter) => Date.parse(shelter.cached_at)));
  const ageMs = Math.max(0, now - newest);
  return { ageMs, stale: ageMs > SHELTER_CACHE_WARN_MS };
}
