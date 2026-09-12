/**
 * The site's route inventory. Data, and nothing else.
 *
 * Separate from `routing.ts` because that module calls `createNavigation`, which reaches
 * `next/navigation` and only resolves inside a Next runtime. Five things need this list and
 * three of them are tests that run outside one: the unit suite, the PII sweep, the axe
 * sweep, the overflow gate and the site navigation itself.
 *
 * Keeping the inventory here means a test can ask "what routes exist" without booting a
 * framework, and — more to the point — means all five ask the *same* list. File 20 shipped
 * two finished screens no user could reach because the navigation and the route tree were
 * two separate sources of truth; this is the shape that prevents the repeat.
 */

export const ROUTES = [
  '/',
  '/allocations',
  '/districts',
  '/schedule',
  '/ledger',
  '/anchors',
  '/grievances',
  '/alerts',
  '/verify',
  '/methodology',
] as const;

export type Route = (typeof ROUTES)[number];

/**
 * A district page, which is the one route with a parameter.
 *
 * Kept beside `ROUTES` rather than inside it because the sweeps need a concrete code to
 * fetch, and a template string in the list would have every one of them invent its own
 * example — which is how a sweep ends up testing a district that does not exist.
 */
export const SAMPLE_DISTRICT_CODE = 'LK-21';
