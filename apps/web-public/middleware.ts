/**
 * Locale negotiation, and nothing else.
 *
 * There is nothing to authenticate. This site has no login, no session and no personal
 * data, which is the product rather than an omission: a journalist checking these figures
 * must not need an account issued by the institution whose numbers they are checking.
 *
 * The matcher excludes `/api` because the public JSON feed and the CSV export are machine
 * endpoints. `/en/api/public/ledger` is not a thing, and a locale-prefixed feed URL would
 * break every script that had already pinned the unprefixed one.
 */

import createMiddleware from 'next-intl/middleware';

import { routing } from './src/i18n/routing';

export default createMiddleware(routing);

export const config = {
  matcher: ['/((?!api|_next|_vercel|.*[.].*).*)'],
};
