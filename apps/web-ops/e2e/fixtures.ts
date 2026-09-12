/**
 * The e2e harness: a signed-in console with a scripted gateway.
 *
 * Two things are faked and it is worth being precise about which:
 *
 * - **The principal cookie.** It is a readable cache of claims, not an authority — the
 *   console authorises nothing from it, and every request is authorised server-side from
 *   the access token. Setting it here puts the browser in the state it would be in after
 *   a real sign-in, without needing a TOTP secret.
 * - **The gateway responses.** Routed in the browser, so the flow under test is the
 *   console's, not five services'.
 *
 * What this cannot prove, and does not claim to: that `incident-svc` refuses an approval
 * without a step-up stamp, or that `ledger-svc` refuses a release with an open grievance.
 * Those are server properties and they are tested in the Python suite against a real
 * database. What these tests prove is that the console asks for the second factor, will
 * not let a plan be approved by pressing Enter, and shows the approver a blocking
 * grievance before they reach the button.
 */

import { test as base, type Page } from '@playwright/test';

export const PLAN_ID = '018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e';
export const ENTITLEMENT_ID = '018f3c2a-0003-7e90-9c2d-000000000003';
export const INCIDENT_ID = '018f3c2a-0001-7e90-9c2d-000000000001';
export const UNSERVABLE_INCIDENT_ID = '018f3c2a-0007-7e90-9c2d-000000000007';
export const RESPONDER_ID = '018f3c2a-0002-7e90-9c2d-000000000002';
export const ALERT_ID = '018f3c2a-0008-7e90-9c2d-000000000008';
export const HAZARD_EVENT_ID = '018f3c2a-0011-7e90-9c2d-000000000011';

export const PRINCIPAL = {
  id: '018f3c2a-0009-7e90-9c2d-000000000009',
  displayName: 'Test Dispatcher',
  roles: ['DISPATCHER', 'DISTRICT_APPROVER'],
  // The real scope strings the platform issues. `entitlement:approve` and `admin:write`
  // were used here once and neither exists, which is how two finished screens ended up
  // unreachable from the navigation - see `tests/auth/test_console_scopes.py`.
  scopes: [
    'incident:read',
    'incident:write',
    'incident:verify',
    'dispatch:commit',
    'alert:read',
    'alert:draft',
    'alert:dispatch',
    'forecast:read',
    'assessment:read',
    'disbursement:release',
    'entitlement:approve_ds',
    'entitlement:approve_district',
    'grievance:read',
    'ledger:read',
    'system:admin',
  ],
  areas: ['LK-11'],
  steppedUpAt: new Date().toISOString(),
};

export function planBody(overrides: Record<string, unknown> = {}) {
  return {
    id: PLAN_ID,
    incident_ids: [INCIDENT_ID],
    responder_ids: ['018f3c2a-0002-7e90-9c2d-000000000002'],
    estimated_duration_min: 45,
    // Six minutes ago, so the gate banner is in its persistent state and the escalation
    // is exercised by the flow rather than only by a unit test.
    proposed_at: new Date(Date.now() - 6 * 60_000).toISOString(),
    proposed_by_agent: 'agent:triage',
    status: 'AWAITING_SIGNOFF',
    signed_off_by: null,
    signed_off_at: null,
    rejection_reason: null,
    ...overrides,
  };
}

export function incidentBody(overrides: Record<string, unknown> = {}) {
  return {
    id: INCIDENT_ID,
    public_ref: 'INC-251128-K4M2XA',
    gn_division_code: 'LK-11-03-045',
    type: 'FLOOD',
    subtype: null,
    summary: null,
    people_at_risk: 42,
    severity: 3,
    status: 'VERIFIED',
    first_reported_at: new Date(Date.now() - 40 * 60_000).toISOString(),
    location_confidence: 0.82,
    // Pallekele, roughly. A fixture with no coordinate would make every incident
    // unplaceable and quietly turn the map tests into tests of the empty case.
    lon: 80.7718,
    lat: 7.2906,
    ...overrides,
  };
}

export function entitlementBody(overrides: Record<string, unknown> = {}) {
  return {
    id: ENTITLEMENT_ID,
    assessment_id: '018f3c2a-0004-7e90-9c2d-000000000004',
    assessment_ref: 'CLM-251128-A1B2C3',
    household_id: '018f3c2a-0005-7e90-9c2d-000000000005',
    gn_division_code: 'LK-11-03-045',
    cost_schedule_version: '2025.11',
    calculated_lkr_cents: 12_500_000,
    calculation_trace: {
      category: 'PARTIAL',
      base_lkr_cents: 10_000_000,
      multiplier: 1.25,
      cap_applied: false,
    },
    calculated_at: new Date(Date.now() - 3 * 3_600_000).toISOString(),
    status: 'APPROVED',
    requires_district_approval: true,
    approvals: [
      {
        level: 'DS',
        approver_id: '018f3c2a-0006-7e90-9c2d-000000000006',
        decision: 'APPROVED',
        decided_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
      },
    ],
    ...overrides,
  };
}

export interface GatewayScript {
  /** Matched against the request URL as a substring, first match wins. */
  readonly match: string;
  readonly status?: number;
  readonly body: unknown;
}

/** Route every gateway call to a scripted answer. Unmatched calls return an empty list. */
export async function scriptGateway(page: Page, script: readonly GatewayScript[]) {
  await page.route('**/gateway/**', async (route) => {
    const url = route.request().url();
    const match = script.find((entry) => url.includes(entry.match));
    await route.fulfill({
      status: match?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(match ? match.body : []),
    });
  });
}

/** Put the browser in the state a real sign-in would leave it in. */
export async function signInAs(page: Page, principal = PRINCIPAL) {
  await page.context().addCookies([
    {
      name: 'sarana_principal',
      value: encodeURIComponent(JSON.stringify(principal)),
      url: 'http://127.0.0.1:3100',
    },
    { name: 'sarana_at', value: 'e2e-access-token', url: 'http://127.0.0.1:3100' },
  ]);
}

export const test = base;
export { expect } from '@playwright/test';

/**
 * The reasoning the triage agent writes into `dispatch_plan.route`.
 *
 * The gate screen renders this expanded by default, so the e2e suite has to be able to
 * put a real one in front of it. The shape is `Plan.as_route_column()`.
 */
export function reasoningBody(overrides: Record<string, unknown> = {}) {
  return {
    routes: [
      {
        responder_id: RESPONDER_ID,
        stops: [{ incident_id: INCIDENT_ID, sequence: 1, eta_minutes: 18.4 }],
        total_minutes: 41,
      },
    ],
    // Deliberately non-empty. The screen must render this prominently, and a fixture
    // without it would let the panel be deleted with every test still green.
    unservable: [
      {
        incident_id: UNSERVABLE_INCIDENT_ID,
        reason: 'NO_CAPABLE_RESPONDER',
        detail: 'no boat-capable team within range',
      },
    ],
    factors: [
      {
        incident_id: INCIDENT_ID,
        rank: 1,
        score: 0.82,
        dispatchability: 0.9,
        dispatchable: true,
        model_version: 'triage-rules-1',
        method: 'RULE',
        factors: { contributions: { people_at_risk: 0.41, severity: 0.3 } },
        explanation: '42 people at risk in a division with road access lost',
      },
    ],
    method: 'ORTOOLS',
    status: 'OPTIMAL',
    rationale: 'Two teams cover the incidents; one needs a boat and none is in range.',
    rationale_method: 'TEMPLATE',
    ...overrides,
  };
}

/** A responder as `GET /responders` returns it. `org`, not `callsign`. */
export function responderBody(overrides: Record<string, unknown> = {}) {
  return {
    id: RESPONDER_ID,
    org: 'Sri Lanka Navy',
    type: 'BOAT',
    capacity: 12,
    status: 'AVAILABLE',
    home_gn_division_id: '018f3c2a-0012-7e90-9c2d-000000000012',
    lon: 80.6337,
    lat: 7.2906,
    ...overrides,
  };
}

/** One division's forecast impact. `drivers` is never empty: a CHECK enforces it. */
export function forecastBody(overrides: Record<string, unknown> = {}) {
  return {
    id: '018f3c2a-0010-7e90-9c2d-000000000010',
    hazard_event_id: HAZARD_EVENT_ID,
    gn_division_id: '018f3c2a-0012-7e90-9c2d-000000000012',
    gn_division_code: 'LK-11-03-045',
    generated_at: new Date(Date.now() - 30 * 60_000).toISOString(),
    valid_from: new Date().toISOString(),
    valid_to: new Date(Date.now() + 24 * 3_600_000).toISOString(),
    impact_class: 4,
    confidence: 0.78,
    lead_time_hours: 26,
    method: 'RULE_THRESHOLD',
    model_version: null,
    drivers: { rainfall_mm_24h: 214, catchment_saturation: 0.91 },
    expected_households_affected: 480,
    expected_road_access_loss: true,
    correlation_id: 'corr-forecast-1',
    ...overrides,
  };
}

/** A drafted alert, ready for the dry run. */
export function alertBody(overrides: Record<string, unknown> = {}) {
  return {
    id: ALERT_ID,
    cap_identifier: `sarana.lk.${ALERT_ID}`,
    status: 'DRAFT',
    requires_human_signoff: false,
    headline: null,
    severity: 3,
    effective_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 12 * 3_600_000).toISOString(),
    created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    ...overrides,
  };
}

/** What a dry run returns. Sends nothing; the console will not send without one. */
export function dryRunBody(overrides: Record<string, unknown> = {}) {
  return {
    dry_run: true,
    targeted: 1203,
    by_channel: { SMS: 1203, PUSH: 402 },
    by_language: { si: 700, ta: 300, en: 203 },
    estimated_cost_lkr: 2105.25,
    exceeds_cap: false,
    cap: 50000,
    ...overrides,
  };
}
