/**
 * The test harness: a screen, in one locale, with a controllable gateway.
 *
 * Every test that renders a console screen needs the same four things — messages, a query
 * client, a tooltip provider, and a `fetch` that answers like the gateway. Assembling
 * them per test file is how three files end up with three slightly different query
 * configurations and one of them passes for the wrong reason.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TooltipProvider } from '@sarana/ui';
import { NextIntlClientProvider } from 'next-intl';
import { render, type RenderResult } from '@testing-library/react';
import type { ReactNode } from 'react';
import { vi } from 'vitest';

import type { Locale } from '@sarana/ts-shared/i18n';
import en from '../../messages/en.json';
import si from '../../messages/si.json';
import ta from '../../messages/ta.json';

export const MESSAGES: Record<Locale, typeof en> = { en, si, ta } as Record<Locale, typeof en>;

/** BCP-47, the same tags the locale layout sets. */
export const LANG_TAGS: Record<Locale, string> = {
  si: 'si-LK',
  ta: 'ta-LK',
  en: 'en-LK',
};

export interface HarnessOptions {
  readonly locale?: Locale;
}

/**
 * A query client with retries and background refetching off.
 *
 * A test that retried a deliberate failure three times would take seconds and then report
 * the last attempt, and a test whose interval fired mid-assertion would be flaky for a
 * reason nobody could reproduce.
 */
export function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false, gcTime: 0, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
}

export function renderScreen(
  ui: ReactNode,
  { locale = 'en' }: HarnessOptions = {},
): RenderResult {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={MESSAGES[locale]}
      timeZone="Asia/Colombo"
      now={new Date('2025-11-27T23:00:00Z')}
    >
      <QueryClientProvider client={testQueryClient()}>
        <TooltipProvider>{ui}</TooltipProvider>
      </QueryClientProvider>
    </NextIntlClientProvider>,
  );
}

/** One canned gateway response, keyed by the path fragment the screen will ask for. */
export interface GatewayRoute {
  readonly match: string;
  readonly status?: number;
  readonly body: unknown;
}

/**
 * Replace `fetch` with a table of canned gateway answers.
 *
 * Matching is by substring on the path, which is enough here and keeps the tables
 * readable. An unmatched request throws rather than returning an empty body: a screen
 * that quietly rendered from `undefined` would pass a test it should fail.
 */
export function installGateway(routes: readonly GatewayRoute[]): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      const route = routes.find((candidate) => url.includes(candidate.match));
      if (!route) {
        throw new Error(
          `no canned gateway route matches ${url}. Add one to the test's route table.`,
        );
      }
      return new Response(JSON.stringify(route.body), {
        status: route.status ?? 200,
        headers: { 'content-type': 'application/json' },
      });
    }),
  );
}

/** A dispatch plan waiting for a decision. Overridable per test. */
export function planFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: '018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e',
    incident_ids: ['018f3c2a-0001-7e90-9c2d-000000000001'],
    responder_ids: ['018f3c2a-0002-7e90-9c2d-000000000002'],
    estimated_duration_min: 45,
    proposed_at: '2025-11-27T22:52:00Z',
    proposed_by_agent: 'agent:triage',
    status: 'AWAITING_SIGNOFF',
    signed_off_by: null,
    signed_off_at: null,
    rejection_reason: null,
    ...overrides,
  };
}

export function incidentFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: '018f3c2a-0001-7e90-9c2d-000000000001',
    public_ref: 'INC-251128-K4M2XA',
    gn_division_code: 'LK-11-03-045',
    type: 'FLOOD',
    subtype: null,
    summary: null,
    people_at_risk: 42,
    severity: 3,
    status: 'VERIFIED',
    first_reported_at: '2025-11-27T22:18:00Z',
    location_confidence: 0.82,
    ...overrides,
  };
}

export function entitlementFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: '018f3c2a-0003-7e90-9c2d-000000000003',
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
      household_cap_lkr_cents: 100_000_000,
      cap_applied: false,
    },
    calculated_at: '2025-11-27T20:00:00Z',
    status: 'APPROVED',
    requires_district_approval: true,
    approvals: [
      {
        level: 'DS',
        approver_id: '018f3c2a-0006-7e90-9c2d-000000000006',
        decision: 'APPROVED',
        decided_at: '2025-11-27T21:00:00Z',
      },
    ],
    ...overrides,
  };
}
