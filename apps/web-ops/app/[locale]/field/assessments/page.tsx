/**
 * `/field/assessments` - the GN officer's read-only web fallback.
 */

import { setRequestLocale } from 'next-intl/server';

import { AssessmentList } from '../../../../src/components/assessments';

export default async function AssessmentsPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <AssessmentList />;
}
