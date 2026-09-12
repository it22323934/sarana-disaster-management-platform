/**
 * `/field/assessments/new` - the web fallback for the Field Companion.
 *
 * The mobile app is the real tool. This exists for the case the brief names it for: the
 * handset is dead, lost, or was never issued. It files an assessment with no photographs
 * and no field position, and it says so before the button rather than feeling equivalent
 * to the app and quietly being worse.
 */

import { setRequestLocale } from 'next-intl/server';

import { AssessmentForm } from '../../../../../../src/components/assessment-form';

export default async function NewAssessmentPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <AssessmentForm />;
}
