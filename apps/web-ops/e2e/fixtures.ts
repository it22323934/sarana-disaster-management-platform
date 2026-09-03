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

export const PRINCIPAL = {
  id: '018f3c2a-0009-7e90-9c2d-000000000009',
  displayName: 'Test Dispatcher',
  roles: ['DISPATCHER', 'DISTRICT_APPROVER'],
  scopes: [
    'incident:read',
    'incident:write',
    'dispatch:commit',
    'disbursement:release',
    'entitlement:approve',
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
