/**
 * The console's gateway: one origin in, five services out.
 *
 * Every call the browser makes goes through here. The handler attaches the access token
 * from the httpOnly cookie, forwards the correlation ID so a console action can be traced
 * through the server logs, and refreshes once on a 401 before giving up.
 *
 * Two things it deliberately does not do:
 *
 * - **It does not decide anything.** No scope check, no role check, no filtering of the
 *   response. Authorisation belongs to the services, which do it from the token against
 *   the area scope in the database. A gateway that also authorised would be a second
 *   place for the rules to live, and the two would drift.
 * - **It does not cache.** Every response is `no-store`. The console shows a triage queue
 *   and a pending-gate count during an incident; a stale one is worse than a slow one.
 */

import { NextResponse, type NextRequest } from 'next/server';

import {
  ACCESS_COOKIE,
  GATEWAY_PATH,
  REFRESH_COOKIE,
  cookieOptions,
} from '../../../src/lib/session';
import { UnroutablePathError, baseUrlFor, upstreamUrl } from '../../../src/lib/services';

export const dynamic = 'force-dynamic';

const CORRELATION_HEADER = 'x-correlation-id';

/** Headers we pass upstream. An allow-list, so nothing from the browser leaks through. */
const FORWARDED_REQUEST_HEADERS = [
  'content-type',
  'accept',
  'accept-language',
  'idempotency-key',
  CORRELATION_HEADER,
];

/** Headers we pass back. Also an allow-list. */
const FORWARDED_RESPONSE_HEADERS = ['content-type', 'content-language', CORRELATION_HEADER];

interface RouteContext {
  readonly params: Promise<{ readonly path: readonly string[] }>;
}

function buildUpstreamHeaders(request: NextRequest, accessToken: string | undefined): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (!headers.has(CORRELATION_HEADER)) {
    headers.set(CORRELATION_HEADER, crypto.randomUUID());
  }
  if (accessToken) headers.set('authorization', `Bearer ${accessToken}`);
  return headers;
}

/**
 * Exchange the refresh token for a new pair.
 *
 * Returns null on any failure, which the caller turns into a 401. Refresh tokens are
 * single-use and rotating, so a failure here means the session is genuinely over rather
 * than something worth retrying.
 */
async function refresh(
  refreshToken: string,
): Promise<{ accessToken: string; refreshToken: string; expiresIn: number } | null> {
  try {
    const response = await fetch(`${baseUrlFor('core-api')}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: 'no-store',
    });
    if (!response.ok) return null;
    const body = (await response.json()) as {
      access_token: string;
      refresh_token: string;
      expires_in: number;
    };
    return {
      accessToken: body.access_token,
      refreshToken: body.refresh_token,
      expiresIn: body.expires_in,
    };
  } catch {
    return null;
  }
}

async function proxy(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  const { path } = await context.params;
  const joined = path.join('/');

  let target: string;
  try {
    target = upstreamUrl(joined);
  } catch (error) {
    if (error instanceof UnroutablePathError) {
      // A 404 with the reason in it, rather than a proxy that guesses and produces a
      // 404 from the wrong service that reads like a missing record.
      return NextResponse.json(
        {
          type: 'https://sarana.lk/errors/unroutable-gateway-path',
          title: 'No service owns this path',
          status: 404,
          detail: error.message,
        },
        { status: 404 },
      );
    }
    throw error;
  }

  const url = new URL(target);
  url.search = request.nextUrl.search;

  const accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  const body =
    request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();

  const send = (token: string | undefined) =>
    fetch(url, {
      method: request.method,
      headers: buildUpstreamHeaders(request, token),
      body,
      cache: 'no-store',
      redirect: 'manual',
    });

  let upstream: Response;
  try {
    upstream = await send(accessToken);
  } catch {
    // The service is down or unreachable. 502 with a Problem Details body, so the
    // console's degraded states can distinguish "backend unreachable" from "you are not
    // allowed" — they call for completely different things on screen.
    return NextResponse.json(
      {
        type: 'https://sarana.lk/errors/upstream-unreachable',
        title: 'The platform is not reachable',
        status: 502,
        detail: `No response from the service that owns /${joined}.`,
      },
      { status: 502 },
    );
  }

  let rotated: Awaited<ReturnType<typeof refresh>> = null;

  if (upstream.status === 401) {
    const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
    if (refreshToken) {
      rotated = await refresh(refreshToken);
      if (rotated) {
        try {
          upstream = await send(rotated.accessToken);
        } catch {
          return NextResponse.json(
            {
              type: 'https://sarana.lk/errors/upstream-unreachable',
              title: 'The platform is not reachable',
              status: 502,
              detail: `No response from the service that owns /${joined}.`,
            },
            { status: 502 },
          );
        }
      }
    }
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  responseHeaders.set('cache-control', 'no-store');

  const response = new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });

  if (rotated) {
    // The rotation happened server-side and the browser never sees either token.
    response.cookies.set(ACCESS_COOKIE, rotated.accessToken, cookieOptions('/', rotated.expiresIn));
    response.cookies.set(
      REFRESH_COOKIE,
      rotated.refreshToken,
      // 14 days. The refresh token's own expiry is the authority; this is the cookie's.
      cookieOptions(GATEWAY_PATH, 60 * 60 * 24 * 14),
    );
  }

  return response;
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
