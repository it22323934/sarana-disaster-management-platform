/**
 * `/totp` - stepping up on its own screen.
 *
 * Rendered inside the console shell, unlike `/login`: the user is signed in, the
 * navigation is meaningful, and the pending-gate banner above it is exactly what they are
 * about to go and act on.
 *
 * The gates also collect the second factor inline, and that stays. This screen is for the
 * other case - a step-up that has expired, or an approver who would rather prove who they
 * are before opening a queue of decisions than in the middle of the first one.
 */

import { setRequestLocale } from 'next-intl/server';

import { StepUpForm } from '../../../src/components/step-up-form';

export default async function StepUpPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <StepUpForm />;
}
