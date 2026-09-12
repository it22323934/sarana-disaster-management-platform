'use server';

/**
 * Sign in, step up, sign out.
 *
 * Server Actions rather than a client-side fetch, because all three set httpOnly cookies
 * and a client cannot. The password and the TOTP code reach the server in the action's
 * payload and are never held in component state after submission.
 */

import { cookies } from 'next/headers';

import {
  ACCESS_COOKIE,
  GATEWAY_PATH,
  PRINCIPAL_COOKIE,
  REFRESH_COOKIE,
  cookieOptions,
  type PrincipalSummary,
} from './session';
import { baseUrlFor } from './services';

const REFRESH_MAX_AGE_SECONDS = 60 * 60 * 24 * 14;

export interface SignInResult {
  readonly ok: boolean;
  /** Safe to show a user. The server guarantees `detail` is. */
  readonly message?: string;
  /** The account has no confirmed second factor and cannot reach either gate yet. */
  readonly mfaEnrolmentRequired?: boolean;
}

interface TokenResponse {
  readonly access_token: string;
  readonly refresh_token: string;
  readonly expires_in: number;
  readonly mfa_enrolment_required?: boolean;
}

async function readDetail(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { detail?: string; title?: string };
    return body.detail ?? body.title;
  } catch {
    return undefined;
  }
}

/**
 * Decode the principal claims from the access token, without verifying it.
 *
 * Unverified on purpose, and it is safe because nothing is authorised from this. It fills
 * the navigation and the "who am I" line in the header; every actual permission is
 * decided by a service from the signed token. Verifying here would mean the console
 * carrying the JWKS and a second copy of the auth rules.
 */
function claimsFromToken(accessToken: string): PrincipalSummary | null {
  try {
    const payload = accessToken.split('.')[1];
    if (!payload) return null;
    const decoded = JSON.parse(
      Buffer.from(payload.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'),
    ) as Record<string, unknown>;

    return {
      id: String(decoded['sub'] ?? ''),
      displayName: String(decoded['name'] ?? decoded['email'] ?? decoded['sub'] ?? ''),
      roles: Array.isArray(decoded['roles']) ? (decoded['roles'] as string[]) : [],
      scopes:
        typeof decoded['scope'] === 'string'
          ? (decoded['scope'] as string).split(' ').filter(Boolean)
          : Array.isArray(decoded['scopes'])
            ? (decoded['scopes'] as string[])
            : [],
      areas: Array.isArray(decoded['areas']) ? (decoded['areas'] as string[]) : [],
      steppedUpAt:
        typeof decoded['step_up_at'] === 'number'
          ? new Date((decoded['step_up_at'] as number) * 1000).toISOString()
          : undefined,
    };
  } catch {
    return null;
  }
}

async function storeSession(tokens: TokenResponse): Promise<void> {
  const jar = await cookies();
  jar.set(ACCESS_COOKIE, tokens.access_token, cookieOptions('/', tokens.expires_in));
  jar.set(REFRESH_COOKIE, tokens.refresh_token, cookieOptions(GATEWAY_PATH, REFRESH_MAX_AGE_SECONDS));

  const principal = claimsFromToken(tokens.access_token);
  if (principal) {
    jar.set(PRINCIPAL_COOKIE, encodeURIComponent(JSON.stringify(principal)), {
      ...cookieOptions('/', REFRESH_MAX_AGE_SECONDS),
      // Readable by the UI. It is a cache of claims the server already asserted, and
      // nothing is authorised from it.
      httpOnly: false,
    });
  }
}

export async function signIn(formData: FormData): Promise<SignInResult> {
  const email = String(formData.get('email') ?? '');
  const password = String(formData.get('password') ?? '');
  const totpCode = String(formData.get('totpCode') ?? '');

  let response: Response;
  try {
    response = await fetch(`${baseUrlFor('core-api')}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        email,
        password,
        totp_code: totpCode.length > 0 ? totpCode : null,
        device_platform: 'web',
      }),
      cache: 'no-store',
    });
  } catch {
    return { ok: false, message: 'The platform is not reachable.' };
  }

  if (!response.ok) {
    // core-api returns the same message for "no such account" and "wrong password", on
    // purpose: distinguishing them turns login into a way of enumerating who works for
    // the state. The console passes that message through unchanged.
    return { ok: false, message: await readDetail(response) };
  }

  const tokens = (await response.json()) as TokenResponse;
  await storeSession(tokens);
  return { ok: true, mfaEnrolmentRequired: tokens.mfa_enrolment_required ?? false };
}

export interface StepUpResult {
  readonly ok: boolean;
  readonly message?: string;
}

/**
 * Re-prove the second factor before a gated action.
 *
 * The response carries a **new access token** with a fresh step-up stamp, so this swaps
 * the access cookie. Forgetting that swap is the subtle failure: the code verifies, the
 * UI says "confirmed", and the next call still goes out with the old token and is
 * refused — which reads to the approver as the platform rejecting their code.
 */
export async function stepUp(code: string): Promise<StepUpResult> {
  const jar = await cookies();
  const accessToken = jar.get(ACCESS_COOKIE)?.value;
  if (!accessToken) return { ok: false, message: 'Your session has ended.' };

  let response: Response;
  try {
    response = await fetch(`${baseUrlFor('core-api')}/api/v1/auth/step-up`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ code }),
      cache: 'no-store',
    });
  } catch {
    return { ok: false, message: 'The platform is not reachable.' };
  }

  if (!response.ok) return { ok: false, message: await readDetail(response) };

  const body = (await response.json()) as { access_token: string; expires_in: number };
  jar.set(ACCESS_COOKIE, body.access_token, cookieOptions('/', body.expires_in));

  const principal = claimsFromToken(body.access_token);
  if (principal) {
    jar.set(PRINCIPAL_COOKIE, encodeURIComponent(JSON.stringify(principal)), {
      ...cookieOptions('/', REFRESH_MAX_AGE_SECONDS),
      httpOnly: false,
    });
  }
  return { ok: true };
}

export async function signOut(): Promise<void> {
  const jar = await cookies();
  const refreshToken = jar.get(REFRESH_COOKIE)?.value;
  const accessToken = jar.get(ACCESS_COOKIE)?.value;

  if (refreshToken && accessToken) {
    try {
      await fetch(`${baseUrlFor('core-api')}/api/v1/auth/logout`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: 'no-store',
      });
    } catch {
      // The local cookies are cleared regardless. A user who clicked sign out on a shared
      // workstation must end up signed out of that browser even if the platform is down.
    }
  }

  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
  jar.delete(PRINCIPAL_COOKIE);
}
