/**
 * The offline capability token, on the device side.
 *
 * Mirrors `core_api.domain.auth.capability`. Seventy-two hours, one GN division, one
 * permission: drafting damage assessments. It cannot approve an entitlement, release
 * funds, read another division or read the incident queue. If the handset is lost, what
 * the finder gains is the ability to write drafts that a DS officer reviews before any of
 * them turns into money.
 *
 * The numbers below are asserted against the server's rather than imported, because the
 * two cannot share a module and a silent drift would show up as a token the server
 * refuses at the worst possible moment - three days into a cut-off division.
 */

/** 72 hours, from `core_api.domain.auth.capability.CAPABILITY_TTL`. */
export const CAPABILITY_TTL_MS = 72 * 60 * 60 * 1000;

/** The entire authority of the token. Anything added is something a lost handset can do. */
export const CAPABILITY_SCOPES: readonly string[] = ['assessment:write'];

/**
 * Refresh this far before expiry.
 *
 * Six hours, not the thirty seconds the online token uses. An officer who will be out of
 * coverage for a day needs the token renewed on the last connection they had, not on the
 * one they were going to have.
 */
export const CAPABILITY_REFRESH_SKEW_MS = 6 * 60 * 60 * 1000;

export interface CapabilityToken {
  readonly token: string;
  readonly gnDivisionCode: string;
  readonly deviceId: string;
  readonly permits: readonly string[];
  /** Epoch milliseconds. */
  readonly expiresAt: number;
}

export type CapabilityStatus =
  | { readonly usable: true; readonly renewSoon: boolean; readonly expiresInMs: number }
  | { readonly usable: false; readonly reason: 'expired' | 'wrong-division' | 'absent' };

/**
 * Whether a token may be used to draft an assessment here, now.
 *
 * `division` is the division the form is being filled in for. A token pinned to one
 * division cannot write in another, and the app checks that before the officer types
 * rather than after the sync fails - a rejection three days later is a rejection of work
 * that cannot be redone.
 */
export function capabilityStatus(
  token: CapabilityToken | null,
  { division, now }: { division: string; now: number },
): CapabilityStatus {
  if (!token) return { usable: false, reason: 'absent' };
  if (token.gnDivisionCode !== division) return { usable: false, reason: 'wrong-division' };
  if (token.expiresAt <= now) return { usable: false, reason: 'expired' };

  return {
    usable: true,
    renewSoon: token.expiresAt - now <= CAPABILITY_REFRESH_SKEW_MS,
    expiresInMs: token.expiresAt - now,
  };
}

/** Whether the token authorises this permission at all. */
export function permits(token: CapabilityToken, scope: string): boolean {
  return token.permits.includes(scope);
}

/** The server's response to `POST /api/v1/auth/capability-token`. */
export interface CapabilityTokenResponse {
  readonly capability_token: string;
  readonly expires_in: number;
  readonly gn_division_code: string;
  readonly permits: readonly string[];
}

export function fromResponse(
  response: CapabilityTokenResponse,
  { deviceId, now }: { deviceId: string; now: number },
): CapabilityToken {
  return {
    token: response.capability_token,
    gnDivisionCode: response.gn_division_code,
    deviceId,
    permits: response.permits,
    expiresAt: now + response.expires_in * 1000,
  };
}
