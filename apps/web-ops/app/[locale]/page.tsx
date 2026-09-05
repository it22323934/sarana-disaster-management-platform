/**
 * `/` — the role-based redirect.
 *
 * Where a person lands says what the console thinks their job is. An approver who lands
 * on the operator's map has to navigate before they can do the one thing they signed in
 * for, and during an incident that is a real cost. The order below is by urgency of the
 * gate each role holds, not alphabetical.
 */

import { redirect } from 'next/navigation';
import { setRequestLocale } from 'next-intl/server';

import { readPrincipal } from '../../src/lib/session';

/**
 * Scope to landing route, most gate-urgent first.
 *
 * Every string here has to be a scope the platform actually issues. `entitlement:approve`
 * was in this table and is not a scope - the real ones are `entitlement:approve_ds` and
 * `entitlement:approve_district` - so a DS approver signing in fell through to the next
 * matching row and landed on the operator's map instead of on the queue holding their
 * signature. Silent, and exactly the failure the navigation had. `tests/auth/test_console_scopes.py`
 * now parses this table too.
 */
const LANDING: ReadonlyArray<readonly [string, string]> = [
  ['dispatch:commit', '/ops/dispatch'],
  ['disbursement:release', '/disbursements'],
  ['entitlement:approve_district', '/approvals'],
  ['entitlement:approve_ds', '/approvals'],
  ['incident:read', '/ops'],
  ['ledger:read', '/audit'],
  ['assessment:write', '/field/assessments'],
];

export default async function RootPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const principal = await readPrincipal();
  if (!principal) redirect(`/${locale}/login`);

  for (const [scope, route] of LANDING) {
    if (principal.scopes.includes(scope)) redirect(`/${locale}${route}`);
  }

  // Signed in, but holding no scope this console has a screen for. Saying so beats
  // redirecting into a page that will only 403 every panel.
  redirect(`/${locale}/ops`);
}
