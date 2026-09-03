/**
 * The browser's view of the API: one origin, and no token anywhere.
 *
 * Deliberately not `@sarana/ts-shared`'s `ApiClient`. That client owns bearer tokens and
 * single-flight refresh, which is exactly what must *not* happen in this browser — the
 * token lives in an httpOnly cookie and the gateway refreshes server-side. Using it here
 * would mean either handing the browser a token or carrying a token-management path that
 * is dead code. It is the right client for the mobile app and for scripts; it is the
 * wrong one here.
 *
 * What is kept is the shape: RFC 9457 Problem Details on every failure, a correlation ID
 * on every request, and zod parsing at the boundary so a contract break surfaces as a
 * named field rather than as `undefined` three components deep.
 */

import { SaranaApiError, problemDetailSchema, type ProblemDetail } from '@sarana/ts-shared/schemas';
import type { z } from 'zod';

export const GATEWAY_PREFIX = '/gateway';

export interface GatewayRequest<TSchema extends z.ZodTypeAny = z.ZodTypeAny> {
  readonly method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  readonly query?: Readonly<Record<string, string | number | boolean | undefined>>;
  readonly body?: unknown;
  readonly schema?: TSchema;
  readonly signal?: AbortSignal;
  /**
   * Required on every POST that creates, moves money or dispatches.
   *
   * Reuse the same key when retrying: the server stores it with the response for 24h and
   * replays it, which is what stops a double-tap on "Release funds" from paying twice.
   */
  readonly idempotencyKey?: string;
}

function buildUrl(path: string, query: GatewayRequest['query']): string {
  const url = new URL(
    `${GATEWAY_PREFIX}/${path.replace(/^\/+/, '')}`,
    // Only the path matters; the origin is discarded by fetch on a same-origin request.
    typeof window === 'undefined' ? 'http://localhost' : window.location.origin,
  );
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }
  return `${url.pathname}${url.search}`;
}

async function readProblem(response: Response, correlationId: string): Promise<ProblemDetail> {
  try {
    const parsed = problemDetailSchema.safeParse(await response.json());
    if (parsed.success) return parsed.data;
  } catch {
    // Fall through: a server that failed before producing a body still has to become a
    // typed error, or every caller needs a second error path.
  }
  return {
    type: 'https://sarana.lk/errors/unparseable',
    title: 'The server returned an error that could not be read',
    status: response.status,
    correlation_id: correlationId,
    errors: [],
  };
}

export async function gatewayFetch<TSchema extends z.ZodTypeAny>(
  path: string,
  options: GatewayRequest<TSchema> & { schema: TSchema },
): Promise<z.infer<TSchema>>;
export async function gatewayFetch(path: string, options?: GatewayRequest): Promise<unknown>;
export async function gatewayFetch(
  path: string,
  options: GatewayRequest = {},
): Promise<unknown> {
  const correlationId = crypto.randomUUID();
  const headers: Record<string, string> = {
    accept: 'application/json',
    'x-correlation-id': correlationId,
  };
  if (options.body !== undefined) headers['content-type'] = 'application/json';
  if (options.idempotencyKey) headers['idempotency-key'] = options.idempotencyKey;

  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
    // The cookie is httpOnly and same-origin; this is what sends it.
    credentials: 'same-origin',
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new SaranaApiError(await readProblem(response, correlationId), response);
  }

  if (response.status === 204) return undefined;

  const json: unknown = await response.json();
  return options.schema ? options.schema.parse(json) : json;
}

/** True when the failure was the platform being unreachable, not a refusal. */
export function isUnreachable(error: unknown): boolean {
  return error instanceof SaranaApiError && error.problem.status === 502;
}

/** True when the session has ended and the user has to sign in again. */
export function isUnauthenticated(error: unknown): boolean {
  return error instanceof SaranaApiError && error.problem.status === 401;
}

/**
 * True when the action needs a fresh second factor.
 *
 * Distinct from a plain 401: the user is signed in and holds the scope, and what is
 * missing is proof of who is at the keyboard. Showing "your session has ended" here
 * would send an approver to the login page for no reason, mid-decision.
 */
export function isStepUpRequired(error: unknown): boolean {
  return (
    error instanceof SaranaApiError &&
    error.problem.status === 401 &&
    (error.problem.type.includes('step-up') || error.problem.type.includes('second-factor'))
  );
}
