/**
 * axe over every console screen, in all three languages.
 *
 * Three locales rather than one, because the failures differ: a Sinhala label can push a
 * control's accessible name into a different shape, and a missing Tamil string produces
 * an empty `aria-label` that English never reveals. Running only English would pass a
 * console that is unusable in two of the three languages it exists to serve.
 *
 * jsdom has no cascade, so axe's `color-contrast` rule cannot evaluate anything here and
 * is disabled explicitly rather than silently skipped. Colour is gated by the design
 * system's `test:contrast`, which measures every token pairing on both surfaces — a
 * stronger check than axe would perform on whatever happens to be on screen.
 */

import axe, { type Result } from 'axe-core';
import { waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Locale } from '@sarana/ts-shared/i18n';

import { Admin } from './admin';
import { ApprovalDetail } from './approval-detail';
import { ApprovalQueue } from './approvals';
import { AlertComposer } from './alert-composer';
import { AlertDispatch } from './alert-dispatch';
import { AlertList, DeliveryPanel } from './alerts';
import { AssessmentForm } from './assessment-form';
import { AssessmentList } from './assessments';
import { AnomalyReview, AuditLedger } from './audit';
import { ChainVerification } from './chain';
import { DisbursementGate } from './disbursement-gate';
import { DispatchGate } from './dispatch-gate';
import { DispatchQueue } from './dispatch-queue';
import { ForecastBoard } from './forecast';
import { IncidentDetail, IncidentList } from './incidents';
import { CommonOperatingPicture } from './common-operating-picture';
import { GrievanceQueue, NotBuilt, ReviewQueue } from './queues';
import { ReleaseQueue } from './release-queue';
import { SignInForm } from './sign-in-form';
import { StepUpForm } from './step-up-form';
import {
  entitlementFixture,
  incidentFixture,
  installGateway,
  planFixture,
  renderScreen,
} from '../test/harness';

vi.mock('../lib/auth-actions', () => ({
  stepUp: vi.fn(async () => ({ ok: true })),
  signIn: vi.fn(async () => ({ ok: true })),
  signOut: vi.fn(),
}));

vi.mock('../i18n/routing', () => ({
  Link: ({ children, ...rest }: { children: ReactNode }) => <a {...rest}>{children}</a>,
  usePathname: () => '/ops/dispatch',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  redirect: vi.fn(),
  getPathname: () => '/',
  routing: { locales: ['si', 'ta', 'en'], defaultLocale: 'en' },
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

const ROUTES = [
  { match: 'dispatch-plans/018f3c2a-7b41', body: planFixture() },
  { match: 'dispatch-plans', body: [planFixture()] },
  { match: 'incidents/018f3c2a-0001', body: incidentFixture() },
  {
    match: 'incidents/queue',
    body: {
      assisted: false,
      banner: 'Assisted triage unavailable - manual ordering',
      ordering: 'triage-rules-1',
      entries: [{ ...incidentFixture(), score: 0.71, model_version: 'triage-rules-1', factors: { severity: 0.4, people_at_risk: 0.31 } }],
    },
  },
  { match: 'responders', body: [] },
  {
    match: 'impact-forecasts',
    body: [
      {
        id: '018f3c2a-0010-7e90-9c2d-000000000010',
        hazard_event_id: '018f3c2a-0011-7e90-9c2d-000000000011',
        gn_division_id: '018f3c2a-0012-7e90-9c2d-000000000012',
        gn_division_code: 'LK-11-03-045',
        generated_at: '2025-11-28T02:00:00Z',
        valid_from: '2025-11-28T02:00:00Z',
        valid_to: '2025-11-29T02:00:00Z',
        impact_class: 4,
        confidence: 0.78,
        lead_time_hours: 26,
        method: 'RULE_THRESHOLD',
        model_version: null,
        drivers: { rainfall_mm_24h: 214, catchment_saturation: 0.91 },
        expected_households_affected: 480,
        expected_road_access_loss: true,
        correlation_id: 'corr-forecast-1',
      },
    ],
  },
  { match: 'anticipatory-triggers', body: [] },
  { match: 'hazard-events', body: [] },
  {
    match: 'admin/users',
    body: [
      {
        id: '018f3c2a-0013-7e90-9c2d-000000000013',
        email: 'ds.kandy@example.lk',
        full_name: 'DS Approver',
        status: 'ACTIVE',
        last_login_at: '2025-11-27T22:00:00Z',
        created_at: '2025-01-05T00:00:00Z',
        mfa_enrolled: false,
        grants: [
          {
            grant_id: '018f3c2a-0014-7e90-9c2d-000000000014',
            role_code: 'DS_APPROVER',
            role_name: { si: 'DS', ta: 'DS', en: 'DS approver' },
            scope_type: 'DS',
            scope_code: 'LK-11-03',
          },
        ],
        scopes: ['entitlement:approve_ds', 'ledger:read'],
      },
    ],
  },
  {
    match: 'admin/roles',
    body: [
      {
        id: '018f3c2a-0015-7e90-9c2d-000000000015',
        code: 'DS_APPROVER',
        name: { si: 'DS', ta: 'DS', en: 'DS approver' },
        scopes: ['entitlement:approve_ds', 'ledger:read'],
        grants_human_gate: false,
      },
    ],
  },
  { match: 'admin/households', body: [] },
  { match: 'admin/gn-divisions', body: [] },
  { match: 'cost-schedules', body: [] },
  { match: 'assessments', body: [] },
  { match: 'entitlements/018f3c2a-0003', body: entitlementFixture() },
  { match: 'grievances', body: [] },
  { match: 'anomalies', body: [] },
  { match: 'disbursements', body: [] },
  { match: 'alerts/018f3c2a-0008/delivery/gaps', body: [] },
  {
    match: 'alerts/018f3c2a-0008/dispatch',
    body: {
      dry_run: true,
      targeted: 1203,
      by_channel: { SMS: 1203, PUSH: 402 },
      by_language: { si: 700, ta: 300, en: 203 },
      estimated_cost_lkr: 2105.25,
      exceeds_cap: false,
      cap: 50000,
    },
  },
  {
    match: 'alerts/018f3c2a-0008/delivery',
    body: {
      targeted: 1203,
      confirmed: 865,
      unconfirmed: 300,
      failed: 20,
      no_channel: 18,
      by_channel: { SMS: { CONFIRMED: 800, FAILED: 20 } },
      by_language: { si: 700, ta: 300, en: 203 },
      summary: '865 of 1,203 targeted households confirmed delivery.',
    },
  },
  {
    match: 'alerts/018f3c2a-0008',
    body: {
      id: '018f3c2a-0008-7e90-9c2d-000000000008',
      cap_identifier: 'sarana.lk.018f3c2a-0008',
      status: 'DRAFT',
      requires_human_signoff: false,
      headline: null,
      severity: 3,
      effective_at: '2025-11-28T04:00:00Z',
      expires_at: '2025-11-28T16:00:00Z',
      created_at: '2025-11-28T03:55:00Z',
    },
  },
  { match: 'alerts', body: [] },
  { match: 'ledger', body: [] },
  { match: 'review-queue', body: [] },
  { match: 'incidents', body: [incidentFixture()] },
  {
    match: 'templates',
    body: [
      {
        id: '018f3c2a-000b-7e90-9c2d-00000000000b',
        code: 'FLOOD_WARNING',
        hazard_type: 'FLOOD',
        severity: 'SEVERE',
        urgency: 'EXPECTED',
        certainty: 'LIKELY',
        body: {
          si: '{gn_division_name} ප්‍රදේශයේ ගංවතුර අනතුරු ඇඟවීම.',
          ta: '{gn_division_name} பகுதியில் வெள்ள எச்சரிக்கை.',
          en: 'Flood warning for {gn_division_name}.',
        },
        reviewed_by_si: '018f3c2a-000c-7e90-9c2d-00000000000c',
        reviewed_by_ta: '018f3c2a-000d-7e90-9c2d-00000000000d',
        reviewed_at: '2025-11-20T00:00:00Z',
        version: 1,
        status: 'PUBLISHED',
      },
    ],
  },
];

interface Screen {
  readonly name: string;
  readonly render: () => ReactNode;
}

const SCREENS: readonly Screen[] = [
  {
    name: 'sign in',
    render: () => <SignInForm locale="en" />,
  },
  {
    name: 'dispatch queue',
    render: () => <DispatchQueue />,
  },
  {
    name: 'dispatch gate',
    render: () => <DispatchGate planId="018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e" />,
  },
  {
    name: 'release queue',
    render: () => <ReleaseQueue />,
  },
  {
    name: 'money gate',
    render: () => (
      <DisbursementGate entitlementId="018f3c2a-0003-7e90-9c2d-000000000003" principal={null} />
    ),
  },
  { name: 'common operating picture', render: () => <CommonOperatingPicture /> },
  { name: 'incident list', render: () => <IncidentList /> },
  {
    name: 'incident detail',
    render: () => <IncidentDetail incidentId="018f3c2a-0001-7e90-9c2d-000000000001" />,
  },
  { name: 'alert list', render: () => <AlertList /> },
  {
    name: 'delivery and gaps',
    render: () => <DeliveryPanel alertId="018f3c2a-0008-7e90-9c2d-000000000008" />,
  },
  { name: 'audit ledger', render: () => <AuditLedger /> },
  { name: 'anomaly review', render: () => <AnomalyReview /> },
  { name: 'review queue', render: () => <ReviewQueue /> },
  { name: 'grievance queue', render: () => <GrievanceQueue /> },
  { name: 'alert composer', render: () => <AlertComposer /> },
  { name: 'chain verification', render: () => <ChainVerification /> },
  { name: 'admin', render: () => <Admin /> },
  { name: 'approvals', render: () => <ApprovalQueue /> },
  { name: 'assessments', render: () => <AssessmentList /> },
  { name: 'not built', render: () => <NotBuilt /> },
  { name: 'forecast board', render: () => <ForecastBoard /> },
  {
    name: 'alert dispatch',
    render: () => <AlertDispatch alertId="018f3c2a-0008-7e90-9c2d-000000000008" />,
  },
  {
    name: 'approval detail',
    render: () => <ApprovalDetail entitlementId="018f3c2a-0003-7e90-9c2d-000000000003" />,
  },
  { name: 'new assessment', render: () => <AssessmentForm /> },
  { name: 'step up', render: () => <StepUpForm /> },
];

const LOCALES: readonly Locale[] = ['en', 'si', 'ta'];

function describeViolation(violation: Result): string {
  const nodes = violation.nodes
    .slice(0, 3)
    .map((node) => `      ${node.html.slice(0, 140)}`)
    .join('\n');
  return `  ${violation.id} (${violation.impact ?? 'unknown'}): ${violation.help}\n${nodes}`;
}

describe('console accessibility', () => {
  const cases = SCREENS.flatMap((definition) =>
    LOCALES.map((locale) => [`${definition.name} [${locale}]`, definition, locale] as const),
  );

  it.each(cases)('has no axe violations: %s', async (_label, definition, locale) => {
    installGateway(ROUTES);
    const { container } = renderScreen(definition.render(), { locale });

    // Wait for the screen to settle. Auditing a skeleton would pass every time and prove
    // nothing about the screen an operator actually uses.
    await waitFor(() => expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0));

    const results = await axe.run(container, {
      rules: {
        'color-contrast': { enabled: false },
        // Screens are mounted into a bare div rather than a document, so page-level
        // landmark rules would fail on the harness rather than on the component.
        region: { enabled: false },
        'page-has-heading-one': { enabled: false },
        'landmark-one-main': { enabled: false },
      },
    });

    expect(
      results.violations.length,
      results.violations.length === 0
        ? ''
        : `${results.violations.length} violation(s):\n${results.violations
            .map(describeViolation)
            .join('\n')}`,
    ).toBe(0);
  });
});
