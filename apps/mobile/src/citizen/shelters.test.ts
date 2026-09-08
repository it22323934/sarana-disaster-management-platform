/**
 * The nearest open shelter.
 *
 * On the emergency path, so it answers with no network and it does not hide anything a
 * person is about to walk to.
 */

import { describe, expect, it } from 'vitest';

import {
  SHELTER_CACHE_WARN_MS,
  distanceMetres,
  nearestShelters,
  shelterCacheAge,
  type Shelter,
} from './shelters.js';

const KANDY = { latitude: 7.2906, longitude: 80.6337 };

function shelter(overrides: Partial<Shelter> & { id: string }): Shelter {
  return {
    name_si: 'පල්ලේකැලේ මහා විද්‍යාලය',
    name_ta: 'பள்ளேகலை மகா வித்தியாலயம்',
    name_en: 'Pallekele Maha Vidyalaya',
    gn_division_code: 'LK-2-05-020-1015',
    latitude: 7.2906,
    longitude: 80.6337,
    capacity: 200,
    occupancy: 40,
    status: 'OPEN',
    cached_at: '2026-09-08T06:00:00.000Z',
    ...overrides,
  };
}

describe('distanceMetres', () => {
  it('is zero for a point against itself', () => {
    expect(distanceMetres(KANDY, KANDY)).toBe(0);
  });

  it('matches a known separation', () => {
    // Kandy to Colombo, about 94km great-circle. Asserted with a tolerance because the
    // point is that the formula is right, not that these two coordinates are.
    const colombo = { latitude: 6.9271, longitude: 79.8612 };
    expect(distanceMetres(KANDY, colombo)).toBeGreaterThan(90_000);
    expect(distanceMetres(KANDY, colombo)).toBeLessThan(100_000);
  });

  it('is symmetric', () => {
    const other = { latitude: 7.3, longitude: 80.7 };
    expect(distanceMetres(KANDY, other)).toBe(distanceMetres(other, KANDY));
  });
});

describe('nearestShelters', () => {
  it('orders by distance, nearest first', () => {
    const list = nearestShelters(
      [
        shelter({ id: 'far', latitude: 7.4, longitude: 80.8 }),
        shelter({ id: 'near', latitude: 7.2907, longitude: 80.6338 }),
      ],
      KANDY,
    );
    expect(list.map((entry) => entry.shelter.id)).toEqual(['near', 'far']);
  });

  it('lists a full shelter rather than hiding it', () => {
    // Hiding it leaves a household walking past the building they were told to go to.
    // Telling them it is full and showing the next one is the whole difference.
    const list = nearestShelters(
      [shelter({ id: 'full', capacity: 100, occupancy: 100 })],
      KANDY,
    );
    expect(list).toHaveLength(1);
    expect(list[0]?.hasSpace).toBe(false);
  });

  it('does not put a full shelter behind a distant empty one', () => {
    // Someone in water wants the nearest roof. The list says whether it has room.
    const list = nearestShelters(
      [
        shelter({ id: 'far-empty', latitude: 7.4, longitude: 80.8, occupancy: 0 }),
        shelter({ id: 'near-full', latitude: 7.2907, longitude: 80.6338, capacity: 50, occupancy: 50 }),
      ],
      KANDY,
    );
    expect(list[0]?.shelter.id).toBe('near-full');
  });

  it('excludes a closed shelter, which is not a place to go', () => {
    expect(nearestShelters([shelter({ id: 'shut', status: 'CLOSED' })], KANDY)).toEqual([]);
  });

  it('still answers with no location, ordered by space and marked as unranked', () => {
    // GPS indoors during a storm is often nothing. Returning an empty list would be the
    // app failing at the one moment it exists for.
    const list = nearestShelters(
      [
        shelter({ id: 'tight', capacity: 100, occupancy: 95 }),
        shelter({ id: 'roomy', capacity: 300, occupancy: 10 }),
      ],
      null,
    );
    expect(list.map((entry) => entry.shelter.id)).toEqual(['roomy', 'tight']);
    // -1 rather than 0: zero would render as "0m away", which is worse than no number.
    expect(list.every((entry) => entry.metres === -1)).toBe(true);
  });

  it('returns at most the requested number', () => {
    const many = Array.from({ length: 10 }, (_, index) =>
      shelter({ id: `s${index}`, latitude: 7.29 + index / 100 }),
    );
    expect(nearestShelters(many, KANDY)).toHaveLength(3);
    expect(nearestShelters(many, KANDY, { limit: 5 })).toHaveLength(5);
  });
});

describe('shelterCacheAge', () => {
  const now = Date.parse('2026-09-08T06:00:00.000Z');

  it('reports nothing for an empty cache', () => {
    expect(shelterCacheAge([], now)).toBeNull();
  });

  it('measures from the newest row', () => {
    const age = shelterCacheAge(
      [
        shelter({ id: 'old', cached_at: '2026-09-01T06:00:00.000Z' }),
        shelter({ id: 'new', cached_at: '2026-09-08T05:00:00.000Z' }),
      ],
      now,
    );
    expect(age?.ageMs).toBe(3_600_000);
    expect(age?.stale).toBe(false);
  });

  it('calls the list stale after six hours', () => {
    // A shelter that opened this morning is not in a list cached last night, and a
    // household that walks to a building that is not open yet has spent the walk.
    const age = shelterCacheAge(
      [shelter({ id: 'a', cached_at: new Date(now - SHELTER_CACHE_WARN_MS - 1).toISOString() })],
      now,
    );
    expect(age?.stale).toBe(true);
  });
});
