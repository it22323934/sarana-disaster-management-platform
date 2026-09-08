/**
 * Where the public figures come from, and why the browser is never told.
 *
 * web-ops proxies every call through its own `/gateway` so the access token can stay in an
 * httpOnly cookie the browser never sees. This app has no token and no cookie, so that
 * reasoning does not apply — and a different one takes its place.
 *
 * **Every read happens on the server and is rendered into the HTML.** The brief requires
 * the core numbers on `/`, `/schedule` and `/ledger` to work with JavaScript disabled,
 * for the journalist behind a locked-down corporate proxy. A client-side fetch cannot
 * satisfy that at any budget, so there is no client-side fetch, so there is nothing for
 * the browser to know a service URL for.
 *
 * The names match the env vars the Python side already uses, so one `.env` configures the
 * whole stack.
 */

export type PublicService = 'core-api' | 'alerting-svc' | 'ledger-svc';

const ENV_VARS: Record<PublicService, string> = {
  'core-api': 'SARANA_CORE_API_URL',
  'alerting-svc': 'SARANA_ALERTING_SVC_URL',
  'ledger-svc': 'SARANA_LEDGER_SVC_URL',
};

const DEFAULT_URLS: Record<PublicService, string> = {
  'core-api': 'http://localhost:8001',
  'alerting-svc': 'http://localhost:8003',
  'ledger-svc': 'http://localhost:8004',
};

export function baseUrlFor(service: PublicService): string {
  return process.env[ENV_VARS[service]] ?? DEFAULT_URLS[service];
}

/** The absolute upstream URL for a public path, `/api/v1` included. */
export function publicUrl(service: PublicService, path: string): string {
  return `${baseUrlFor(service)}/api/v1/${path.replace(/^\/+/, '')}`;
}

/**
 * How long a rendered page may be reused before it is regenerated.
 *
 * Five minutes, from the brief. It is the one number that decides both how fresh the site
 * is and how much load reaches five Python services from a public URL that may be on a
 * news front page, so it lives here rather than being repeated per route.
 *
 * The ledger feed and the exports opt out of it deliberately — see `revalidate` in those
 * route handlers.
 */
export const REVALIDATE_SECONDS = 300;

/**
 * Boundaries are cached for an hour, and the figures over them for five minutes.
 *
 * Administrative boundaries change on a timescale of years. Revalidating a 400 KB GeoJSON
 * payload every five minutes alongside numbers that actually move would spend most of the
 * site's bandwidth redownloading a map that had not changed.
 */
export const GEOMETRY_REVALIDATE_SECONDS = 3600;
