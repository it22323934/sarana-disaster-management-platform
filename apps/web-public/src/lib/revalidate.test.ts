/**
 * The `revalidate` literals in the route files still match the documented constants.
 *
 * Next statically analyses `export const revalidate` and rejects an imported identifier
 * ("Unknown identifier REVALIDATE_SECONDS at revalidate"), so each route carries a literal.
 * That leaves twelve copies of one number, which is exactly the shape that drifts: somebody
 * tunes the overview to sixty seconds during an incident and nine other pages stay at five
 * minutes, so two pages of the same site disagree about how old their figures are and
 * neither says which.
 *
 * `REVALIDATE_SECONDS` stays the documented value and this test holds the copies to it.
 *
 * It also asserts the routes the brief lists actually exist as files. That guard is here
 * because file 20 shipped two finished screens that no user could reach, and the cheapest
 * place to catch the reverse — a route in the navigation with no page behind it — is here.
 */

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { ROUTES } from '../i18n/routes';
import { GEOMETRY_REVALIDATE_SECONDS, REVALIDATE_SECONDS } from './services';

const APP = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'app');

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const REVALIDATE = /export const revalidate = (\d+);/;

describe('revalidate literals', () => {
  const pages = walk(APP).filter((file) => file.endsWith('page.tsx'));

  it('finds every page file, so this test cannot pass by looking at nothing', () => {
    // One per route plus the district detail page.
    expect(pages.length).toBe(ROUTES.length + 1);
  });

  for (const page of walk(APP).filter((file) => file.endsWith('page.tsx'))) {
    const relative = page.slice(APP.length + 1).replace(/\\/g, '/');

    it(`${relative} revalidates at REVALIDATE_SECONDS`, () => {
      const match = REVALIDATE.exec(readFileSync(page, 'utf8'));
      expect(match, `${relative} declares no revalidate. ISR is not optional on this site.`)
        .not.toBeNull();
      expect(Number(match?.[1])).toBe(REVALIDATE_SECONDS);
    });
  }

  it('the GeoJSON route revalidates at the geometry interval, not the figures interval', () => {
    // Boundaries change on a timescale of years. Revalidating a large payload every five
    // minutes alongside numbers that actually move would spend most of the site's
    // bandwidth redownloading a map that had not changed.
    const route = join(APP, 'api', 'public', 'districts.geojson', 'route.ts');
    const match = REVALIDATE.exec(readFileSync(route, 'utf8'));
    expect(Number(match?.[1])).toBe(GEOMETRY_REVALIDATE_SECONDS);
  });
});

describe('every route in the navigation has a page behind it', () => {
  for (const route of ROUTES) {
    it(`${route} exists`, () => {
      const path = route === '/' ? join(APP, '[locale]', 'page.tsx') : join(APP, '[locale]', ...route.slice(1).split('/'), 'page.tsx');
      expect(existsSync(path), `${route} is in the navigation and has no page file`).toBe(true);
    });
  }
});
