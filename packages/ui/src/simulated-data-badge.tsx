/**
 * The Simulated data badge.
 *
 * Every UI surface rendering mock-derived data shows this. There is no live integration
 * with any Sri Lankan government system: the meteorology feed, NBRO bulletins, the
 * household registry, NIC verification, the bank disbursement rail and the telco gateway
 * are all mocks. A demo must never let a viewer believe otherwise.
 *
 * It lives in the shared package, not in each app, so the wording and the styling cannot
 * drift and no surface can quietly drop it.
 */

import type { JSX } from 'react';

import type { Locale } from '@sarana/ts-shared/i18n';

const LABEL: Record<Locale, string> = {
  si: 'අනුකරණය කළ දත්ත',
  ta: 'உருவகப்படுத்தப்பட்ட தரவு',
  en: 'Simulated data',
};

const EXPLANATION: Record<Locale, string> = {
  si: 'මෙම දත්ත රජයේ පද්ධතියක අනුකරණයකින් ලැබේ, සජීවී මූලාශ්‍රයකින් නොවේ.',
  ta: 'இந்தத் தரவு அரசாங்க அமைப்பின் உருவகப்படுத்தலிலிருந்து வருகிறது, நேரடி மூலத்திலிருந்து அல்ல.',
  en: 'This data comes from a simulated government system, not a live source.',
};

export interface SimulatedDataBadgeProps {
  readonly locale?: Locale;
  /** Which mock produced the data, e.g. `dept-meteorology`. Shown on hover. */
  readonly source?: string;
  readonly className?: string;
}

export function SimulatedDataBadge({
  locale = 'en',
  source,
  className,
}: SimulatedDataBadgeProps): JSX.Element {
  const explanation = source
    ? `${EXPLANATION[locale]} (${source})`
    : EXPLANATION[locale];

  return (
    <span
      className={className}
      data-sarana-simulated="true"
      title={explanation}
      aria-label={explanation}
      role="status"
    >
      {LABEL[locale]}
    </span>
  );
}
