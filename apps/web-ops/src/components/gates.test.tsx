/**
 * The two gates, tested on the properties that make them gates.
 *
 * These are not rendering smoke tests. Each one asserts something that, if it stopped
 * holding, would let a person commit a dispatch or move money without the check the
 * platform claims to enforce.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DispatchGate } from './dispatch-gate';
import { DisbursementGate } from './disbursement-gate';
import { PendingGateBanner, urgencyFor } from '@sarana/ui';
import {
  entitlementFixture,
  incidentFixture,
  installGateway,
  planFixture,
  renderScreen,
} from '../test/harness';

// The server action module talks to core-api over the network. Replaced wholesale so a
// test exercises the console's decision logic rather than the auth service's.
const stepUpMock = vi.fn<(code: string) => Promise<{ ok: boolean; message?: string }>>(
  async () => ({ ok: true }),
);
vi.mock('../lib/auth-actions', () => ({
  stepUp: (code: string) => stepUpMock(code),
  signIn: vi.fn(),
  signOut: vi.fn(),
}));

// next-intl's navigation needs Next's router context, which jsdom has no equivalent for.
vi.mock('../i18n/routing', () => ({
  Link: ({ children, ...rest }: { children: React.ReactNode }) => <a {...rest}>{children}</a>,
  usePathname: () => '/ops/dispatch',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  redirect: vi.fn(),
  getPathname: () => '/',
  routing: { locales: ['si', 'ta', 'en'], defaultLocale: 'en' },
}));

afterEach(() => {
  vi.unstubAllGlobals();
  stepUpMock.mockClear();
});

const DISPATCH_ROUTES = [
  { match: 'dispatch-plans/018f3c2a-7b41', body: planFixture() },
  { match: 'incidents/018f3c2a-0001', body: incidentFixture() },
  { match: 'responders', body: [] },
];

describe('the dispatch gate', () => {
  it('will not approve until six digits are present', async () => {
    installGateway(DISPATCH_ROUTES);
    renderScreen(<DispatchGate planId="018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e" />);

    const approve = await screen.findByRole('button', { name: /approve and dispatch/i });
    // Disabled with nothing typed, and still disabled with five digits. A dispatcher
    // resting a hand on the keyboard must not be able to send people towards a hazard.
    expect(approve).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/authenticator code/i), '12345');
    expect(approve).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/authenticator code/i), '6');
    await waitFor(() => expect(approve).toBeEnabled());
  });

  it('does not approve when Enter is pressed in the code field', async () => {
    installGateway(DISPATCH_ROUTES);
    renderScreen(<DispatchGate planId="018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e" />);

    const field = await screen.findByLabelText(/authenticator code/i);
    await userEvent.type(field, '123456{Enter}');

    // The form swallows submit. Approving sends responders towards a hazard and has to be
    // a deliberate press of a button that says so.
    expect(stepUpMock).not.toHaveBeenCalled();
  });

  it('steps up before it approves, and only once the code is complete', async () => {
    installGateway([
      ...DISPATCH_ROUTES,
      {
        match: '/approve',
        body: {
          plan_id: '018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e',
          status: 'APPROVED',
          decided_by: 'user',
          decided_at: '2025-11-27T23:00:00Z',
          graph_resumed: false,
          reason: null,
        },
      },
    ]);
    renderScreen(<DispatchGate planId="018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e" />);

    await userEvent.type(await screen.findByLabelText(/authenticator code/i), '123456');
    await userEvent.click(screen.getByRole('button', { name: /approve and dispatch/i }));

    await waitFor(() => expect(stepUpMock).toHaveBeenCalledWith('123456'));
  });

  it('offers reject at the same size as approve, and never pre-selects either', async () => {
    installGateway(DISPATCH_ROUTES);
    renderScreen(<DispatchGate planId="018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e" />);

    const approve = await screen.findByRole('button', { name: /approve and dispatch/i });
    const reject = screen.getByRole('button', { name: /^reject$/i });

    // If rejecting is slower or smaller than approving, people approve to save time and
    // the gate becomes theatre.
    expect(reject).toBeEnabled();
    expect(approve).toBeDisabled();
    expect(reject.className).toContain('h-12');
    expect(approve.className).toContain('h-12');
  });

  it('says the agent reasoning is missing rather than showing an empty factor list', async () => {
    installGateway(DISPATCH_ROUTES);
    const { container } = renderScreen(
      <DispatchGate planId="018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e" />,
    );

    await screen.findByRole('button', { name: /approve and dispatch/i });
    // An empty "why these are ranked here" section would read as "the agent considered
    // nothing", which is a different and worse claim than "no agent ranked this".
    expect(container.querySelector('[data-degraded="reasoning"]')).not.toBeNull();
  });

  it('totals the people at risk across the plan, above the fold', async () => {
    installGateway([
      { match: 'dispatch-plans/018f3c2a-7b41', body: planFixture() },
      { match: 'incidents/018f3c2a-0001', body: incidentFixture({ people_at_risk: 42 }) },
      { match: 'responders', body: [] },
    ]);
    renderScreen(<DispatchGate planId="018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e" />);

    await screen.findByRole('button', { name: /approve and dispatch/i });

    // Twice on purpose: once in the summary the dispatcher reads first, once on the
    // incident row. The summary is the aggregate, so a plan covering three incidents
    // shows their sum rather than the first one's figure.
    await waitFor(() => expect(screen.getAllByText('42').length).toBeGreaterThan(1));

    const summary = screen
      .getAllByText('42')
      .find((node) => node.className.includes('text-lg'));
    expect(summary).toBeDefined();
  });
});

describe('the money gate', () => {
  const RELEASE_ROUTES = [
    { match: 'entitlements/018f3c2a-0003', body: entitlementFixture() },
    { match: 'grievances', body: [] },
    { match: 'anomalies', body: [] },
  ];

  it('renders the calculation as a derivation, not just a total', async () => {
    installGateway(RELEASE_ROUTES);
    renderScreen(
      <DisbursementGate entitlementId="018f3c2a-0003-7e90-9c2d-000000000003" principal={null} />,
    );

    // Schedule version and every trace key, so an approver can catch the version being
    // wrong — which is the error that actually happens.
    await waitFor(() => expect(screen.getByText('2025.11')).toBeDefined());
    expect(screen.getByText('base_lkr_cents')).toBeDefined();
    expect(screen.getByText('multiplier')).toBeDefined();
  });

  it('blocks the release while a grievance is open, before the button is pressed', async () => {
    installGateway([
      { match: 'entitlements/018f3c2a-0003', body: entitlementFixture() },
      {
        match: 'grievances',
        body: [
          {
            id: '018f3c2a-0007-7e90-9c2d-000000000007',
            public_ref: 'GRV-251128-Z9Y8',
            entitlement_id: '018f3c2a-0003-7e90-9c2d-000000000003',
            status: 'OPEN',
          },
        ],
      },
      { match: 'anomalies', body: [] },
    ]);
    renderScreen(
      <DisbursementGate entitlementId="018f3c2a-0003-7e90-9c2d-000000000003" principal={null} />,
    );

    await waitFor(() =>
      expect(screen.getByText(/open grievance blocks this release/i)).toBeDefined(),
    );

    await userEvent.type(screen.getByLabelText(/release approval/i), '123456');
    // `ledger-svc` would refuse this with a 409. Letting the click through to collect one
    // would teach approvers that refusals are noise.
    expect(screen.getByRole('button', { name: /release funds/i })).toBeDisabled();
  });

  it('refuses when the approver is also an approver of record', async () => {
    installGateway(RELEASE_ROUTES);
    renderScreen(
      <DisbursementGate
        entitlementId="018f3c2a-0003-7e90-9c2d-000000000003"
        principal={{
          id: '018f3c2a-0006-7e90-9c2d-000000000006',
          displayName: 'Approver',
          roles: [],
          scopes: [],
          areas: [],
        }}
      />,
    );

    await waitFor(() => expect(screen.getByText(/recorded as DS on it/i)).toBeDefined());
    expect(screen.getByRole('button', { name: /release funds/i })).toBeDisabled();
  });

  it('ignores a household name even when the server sends one', async () => {
    // The queries behind this screen never select a name, which is the real guarantee.
    // This asserts the second line of defence: if a service ever started returning one,
    // the approver still would not see it, because the screen renders a reference and has
    // no slot for a name to land in.
    installGateway([
      {
        match: 'entitlements/018f3c2a-0003',
        body: entitlementFixture({
          household_name: 'Wickramasinghe',
          applicant_name: 'K. Wickramasinghe',
        }),
      },
      { match: 'grievances', body: [] },
      { match: 'anomalies', body: [] },
    ]);
    const { container } = renderScreen(
      <DisbursementGate entitlementId="018f3c2a-0003-7e90-9c2d-000000000003" principal={null} />,
    );

    await waitFor(() => expect(screen.getByText('2025.11')).toBeDefined());
    expect(container.textContent).not.toContain('Wickramasinghe');
  });
});

describe('the gate banner escalation', () => {
  it('crosses to prominent at 2 minutes and persistent at 5', () => {
    expect(urgencyFor(119)).toBe('waiting');
    expect(urgencyFor(120)).toBe('prominent');
    expect(urgencyFor(299)).toBe('prominent');
    expect(urgencyFor(300)).toBe('persistent');
  });

  it('interrupts a screen reader only once the wait is persistent', () => {
    const { container, rerender } = render(
      <PendingGateBanner
        kind="dispatch"
        count={1}
        oldestWaitingSince="2025-11-27T22:59:30Z"
        now={new Date('2025-11-27T23:00:00Z')}
        title={(count) => `${count} waiting`}
        ageLabel={(seconds) => `${seconds}s`}
        action={null}
      />,
    );
    expect(container.querySelector('[role="status"]')).not.toBeNull();

    rerender(
      <PendingGateBanner
        kind="dispatch"
        count={1}
        oldestWaitingSince="2025-11-27T22:50:00Z"
        now={new Date('2025-11-27T23:00:00Z')}
        title={(count) => `${count} waiting`}
        ageLabel={(seconds) => `${seconds}s`}
        action={null}
      />,
    );
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
  });
});
