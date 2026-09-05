/**
 * Which of the five services owns which path.
 *
 * The console talks to **one origin** — its own `/gateway` — and a Next route handler
 * forwards each call to the service that owns it. Three reasons, and the third is the
 * one that matters:
 *
 * 1. Five services on five ports means five CORS configurations, each of which has to
 *    allow credentials from the console's origin. That is five places to get wrong.
 * 2. The browser would need to know the port map, which makes the deployment topology a
 *    frontend concern. Behind an ALB in AWS it is not one.
 * 3. **The access token never reaches the browser.** It lives in an httpOnly cookie the
 *    gateway reads server-side. A token in `localStorage` is exfiltrable by any XSS on
 *    any page, and this console releases money and dispatches responders. That is not a
 *    risk to take for the convenience of a client-side fetch.
 *
 * The mapping is by first path segment, which is unambiguous today: no two services
 * expose the same collection. `assertRoutable` fails loudly rather than defaulting,
 * because a silent default would send an unrecognised path to core-api and produce a 404
 * that looks like a missing record rather than a missing route.
 */

export type ServiceName =
  | 'core-api'
  | 'incident-svc'
  | 'alerting-svc'
  | 'ledger-svc'
  | 'agent-svc';

/** Env var per service, matching the names the Python side already uses. */
const ENV_VARS: Record<ServiceName, string> = {
  'core-api': 'SARANA_CORE_API_URL',
  'incident-svc': 'SARANA_INCIDENT_SVC_URL',
  'alerting-svc': 'SARANA_ALERTING_SVC_URL',
  'ledger-svc': 'SARANA_LEDGER_SVC_URL',
  'agent-svc': 'SARANA_AGENT_SVC_URL',
};

const DEFAULT_URLS: Record<ServiceName, string> = {
  'core-api': 'http://localhost:8001',
  'incident-svc': 'http://localhost:8002',
  'alerting-svc': 'http://localhost:8003',
  'ledger-svc': 'http://localhost:8004',
  'agent-svc': 'http://localhost:8005',
};

/**
 * First path segment to owning service.
 *
 * Everything user-facing is mounted under `/api/v1` on every service, so the gateway
 * prepends that rather than each caller carrying it.
 */
const OWNERS: Readonly<Record<string, ServiceName>> = {
  // core-api
  auth: 'core-api',
  admin: 'core-api',
  audit: 'core-api',
  meta: 'core-api',
  rg: 'core-api',
  // incident-svc
  incidents: 'incident-svc',
  reports: 'incident-svc',
  responders: 'incident-svc',
  'dispatch-plans': 'incident-svc',
  'review-queue': 'incident-svc',
  // alerting-svc
  alerts: 'alerting-svc',
  templates: 'alerting-svc',
  coverage: 'alerting-svc',
  // ledger-svc
  assessments: 'ledger-svc',
  entitlements: 'ledger-svc',
  disbursements: 'ledger-svc',
  grievances: 'ledger-svc',
  anomalies: 'ledger-svc',
  ledger: 'ledger-svc',
  'cost-schedules': 'ledger-svc',
  // agent-svc
  agents: 'agent-svc',
  // Hazard events live in agent-svc's schema because the forecast agent declares them.
  'hazard-events': 'agent-svc',
};

export class UnroutablePathError extends Error {
  constructor(readonly path: string) {
    super(
      `no SARANA service owns '/${path}'. Add it to OWNERS in src/lib/services.ts, or ` +
        'fix the caller. The gateway refuses rather than guessing.',
    );
    this.name = 'UnroutablePathError';
  }
}

export function serviceFor(path: string): ServiceName {
  const first = path.replace(/^\/+/, '').split('/')[0] ?? '';
  const owner = OWNERS[first];
  if (!owner) throw new UnroutablePathError(path);
  return owner;
}

export function baseUrlFor(service: ServiceName): string {
  return process.env[ENV_VARS[service]] ?? DEFAULT_URLS[service];
}

/** The absolute upstream URL for a gateway path, `/api/v1` included. */
export function upstreamUrl(path: string): string {
  const clean = path.replace(/^\/+/, '');
  return `${baseUrlFor(serviceFor(clean))}/api/v1/${clean}`;
}
