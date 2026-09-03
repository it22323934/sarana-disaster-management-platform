/**
 * Locale negotiation, and nothing else.
 *
 * This middleware does not authenticate. It is tempting to redirect signed-out users to
 * the login page here, and it would be wrong: middleware runs on the edge with no access
 * to the services, so the only thing it could check is the presence of a cookie — which
 * proves nothing about whether the token is valid, in scope, or revoked. A console that
 * routed on cookie *presence* would show its shell to a user whose session ended, and
 * every panel inside it would then fail separately.
 *
 * Authorisation is done where the answer is knowable: in the layouts and route handlers,
 * against the token, by the services.
 */

import createMiddleware from 'next-intl/middleware';

import { routing } from './src/i18n/routing';

export default createMiddleware(routing);

export const config = {
  // Everything except the gateway, Next's internals and static files. The gateway must
  // not be locale-prefixed: it is an API, and `/si/gateway/incidents` is not a thing.
  matcher: ['/((?!gateway|api|_next|_vercel|.*[.].*).*)'],
};
