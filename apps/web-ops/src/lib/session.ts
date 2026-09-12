import 'server-only';

/**
 * The console's session, held in httpOnly cookies.
 *
 * Three cookies, and the split is deliberate:
 *
 * - `sarana_at` — the access token. `httpOnly`, so no script on any page can read it.
 * - `sarana_rt` — the refresh token. Same, and scoped to the gateway path so it is not
 *   sent on every navigation.
 * - `sarana_principal` — a *readable* summary of who is signed in: id, roles, scopes,
 *   display name, and when the last step-up was. Not httpOnly, because the UI has to
 *   decide which navigation items to render, and round-tripping that to the server on
 *   every render would make the shell a client-server waterfall.
 *
 * The third one is a cache of claims the server already asserted, never an authority.
 * Nothing is authorised by reading it: every request is authorised server-side from the
 * token, and a user who edits their own principal cookie to add a scope gets a 403 from
 * the service, not a wider console.
 */

import { cookies } from 'next/headers';

import { STEP_UP_WINDOW_SECONDS } from './step-up';

export const ACCESS_COOKIE = 'sarana_at';
export const REFRESH_COOKIE = 'sarana_rt';
export const PRINCIPAL_COOKIE = 'sarana_principal';

/** Where the refresh cookie is sent. Narrow, because it is the long-lived one. */
export const GATEWAY_PATH = '/gateway';

export interface PrincipalSummary {
  readonly id: string;
  readonly displayName: string;
  readonly roles: readonly string[];
  readonly scopes: readonly string[];
  /** Area codes this principal is scoped to, e.g. `["LK-11"]` or `["LK"]`. */
  readonly areas: readonly string[];
  /** ISO-8601 of the last second-factor verification, when there has been one. */
  readonly steppedUpAt?: string;
}

// Re-exported so existing server-side callers keep one import. The constant itself lives
// in `step-up.ts`, which carries no `server-only`, because `/totp` is a client component
// and has to quote the same window back to the user.
export { STEP_UP_WINDOW_SECONDS } from './step-up';

export async function readAccessToken(): Promise<string | undefined> {
  return (await cookies()).get(ACCESS_COOKIE)?.value;
}

export async function readRefreshToken(): Promise<string | undefined> {
  return (await cookies()).get(REFRESH_COOKIE)?.value;
}

export async function readPrincipal(): Promise<PrincipalSummary | null> {
  const raw = (await cookies()).get(PRINCIPAL_COOKIE)?.value;
  if (!raw) return null;
  try {
    return JSON.parse(decodeURIComponent(raw)) as PrincipalSummary;
  } catch {
    // A malformed cookie means signed out, not an error page. It is a cache.
    return null;
  }
}

export function isStepUpFresh(
  principal: PrincipalSummary | null,
  now: Date = new Date(),
): boolean {
  if (!principal?.steppedUpAt) return false;
  const age = (now.getTime() - new Date(principal.steppedUpAt).getTime()) / 1000;
  return age >= 0 && age < STEP_UP_WINDOW_SECONDS;
}

export function hasScope(principal: PrincipalSummary | null, scope: string): boolean {
  return principal?.scopes.includes(scope) ?? false;
}

/** Cookie options shared by all three. `secure` follows the deployment, not the code. */
export function cookieOptions(path: string, maxAgeSeconds: number) {
  return {
    httpOnly: true,
    sameSite: 'lax' as const,
    // Behind the ALB this is https; locally it is not, and a `secure` cookie would
    // silently never be set, which presents as "login does nothing".
    secure: process.env.NODE_ENV === 'production',
    path,
    maxAge: maxAgeSeconds,
  };
}
