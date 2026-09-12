/**
 * How long a step-up is good for.
 *
 * Its own module, with no `server-only`, because both sides need it: `session.ts` reads it
 * to decide whether the header shows a fresh confirmation, and `/totp` reads it to tell
 * the user how long the confirmation they just made will last. Leaving it in `session.ts`
 * meant a client component importing a `server-only` module, which fails the build rather
 * than the type check — a late and confusing way to discover a one-line dependency.
 *
 * Five minutes, matching what `ledger-svc` and `incident-svc` enforce. The console shows
 * this so an approver knows whether the next gate will ask again; it never *decides*
 * anything from it. The services re-check on every gated call, which is the check that
 * counts.
 */

export const STEP_UP_WINDOW_SECONDS = 300;

/** The same window in minutes, for the sentences that quote it to a person. */
export const STEP_UP_WINDOW_MINUTES = STEP_UP_WINDOW_SECONDS / 60;
