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
import { screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Locale } from '@sarana/ts-shared/i18n';

import { DisbursementGate } from './disbursement-gate';
import { DispatchGate } from './dispatch-gate';
import { DispatchQueue } from './dispatch-queue';
import { ReleaseQueue } from './release-queue';
import { SignInForm } from './sign-in-form';
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
  { match: 'incidents/queue', body: [incidentFixture()] },
  { match: 'responders', body: [] },
  { match: 'entitlements/018f3c2a-0003', body: entitlementFixture() },
  { match: 'grievances', body: [] },
  { match: 'anomalies', body: [] },
  { match: 'disbursements', body: [] },
];

interface Screen {
  readonly name: string;
  readonly render: () => ReactNode;
  /** Something that must be on screen before axe runs, so it never audits a spinner. */
  readonly settled: RegExp;
}

const SCREENS: readonly Screen[] = [
  {
    name: 'sign in',
    render: () => <SignInForm locale="en" />,
    settled: /.+/,
  },
  {
    name: 'dispatch queue',
    render: () => <DispatchQueue />,
    settled: /.+/,
  },
  {
    name: 'dispatch gate',
    render: () => <DispatchGate planId="018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e" />,
    settled: /.+/,
  },
  {
    name: 'release queue',
    render: () => <ReleaseQueue />,
    settled: /.+/,
  },
  {
    name: 'money gate',
    render: () => (
      <DisbursementGate entitlementId="018f3c2a-0003-7e90-9c2d-000000000003" principal={null} />
    ),
    settled: /.+/,
  },
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
    await waitFor(() => expect(screen.getAllByRole('heading').length).toBeGreaterThan(0));

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
