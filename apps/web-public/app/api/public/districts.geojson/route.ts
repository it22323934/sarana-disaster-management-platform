/**
 * `/api/public/districts.geojson` — the boundaries the choropleth fetches.
 *
 * A proxy rather than a direct browser call to core-api, and the reason is not CORS.
 *
 * **The browser is never told a service URL on this site.** Every other read happens on the
 * server and is rendered into the HTML, which is what makes the core numbers work with
 * scripting off. The map is the one thing a browser genuinely has to load for itself, and
 * pointing it at `http://core-api:8001` would put the internal topology into a page anyone
 * can view-source and would fail the moment the deployment moved a port.
 *
 * Cached hard. Administrative boundaries change on a timescale of years, and this payload
 * is the largest thing the site serves — revalidating it every five minutes alongside
 * numbers that actually move would spend most of the site's bandwidth redownloading a map
 * that had not changed.
 */

import { NextResponse } from 'next/server';

import { getDistrictGeoJson } from '../../../../src/lib/public-api';
import { GEOMETRY_REVALIDATE_SECONDS } from '../../../../src/lib/services';

/**
 * One hour, matching `GEOMETRY_REVALIDATE_SECONDS`.
 *
 * A literal for the same reason the pages use one: Next will not resolve an imported
 * identifier here. `src/lib/revalidate.test.ts` holds the two in agreement.
 */
export const revalidate = 3600;

export async function GET(): Promise<NextResponse> {
  const geojson = await getDistrictGeoJson();

  if (!geojson.ok) {
    // The map treats any non-200 as "no map" and renders the note pointing at the table,
    // so this body is for a developer reading a network tab rather than for the page.
    return NextResponse.json(
      { error: 'upstream_unavailable', reason: geojson.reason },
      { status: 502, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  return NextResponse.json(geojson.data, {
    headers: {
      'Cache-Control': `public, max-age=${GEOMETRY_REVALIDATE_SECONDS}`,
      'Access-Control-Allow-Origin': '*',
    },
  });
}
