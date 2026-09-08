'use client';

/**
 * The quiet-hours notice.
 *
 * Build file 20 asks that the composer show "quiet-hours state, with the rule and whether
 * this alert bypasses it". The rule itself lives in `agent_svc.agents.warning.channels`
 * and is enforced there; this renders a display of it, and the distinction matters:
 *
 * - Nothing here decides anything. The warning agent defers the SMS whatever this
 *   component shows. If the two disagree the agent is right.
 * - It is mirrored for the same reason the SMS segment count is: the operator has to know
 *   *before* sending that a watch-level alert at 2am will sit until 06:00. A state they
 *   can only discover from the delivery panel the next morning is a state they find out
 *   about too late to reword or re-time the message.
 *
 * The rule moved to `@sarana/ts-shared/domain` when the mobile app needed the same answer
 * to decide whether a push may wake somebody. Two copies of a rule with a half-hour
 * timezone trap in it is one copy too many; `quiet-hours.test.ts` still walks the clock
 * through a full day against it from here.
 */

import { cn } from '@sarana/ui';
import { formatTime } from '@sarana/ts-shared/format';
import {
  BYPASS_FROM_CLASS,
  QUIET_END_HOUR,
  QUIET_HOURS_CHANNELS,
  QUIET_RELEASE_HOUR,
  QUIET_START_HOUR,
  colomboHour,
  colomboParts,
  inQuietHours,
  quietHoursState,
  releaseAt,
  type QuietHoursState,
} from '@sarana/ts-shared/domain';
import type { Locale } from '@sarana/ts-shared/i18n';
import { useTranslations } from 'next-intl';

// Re-exported so the existing imports across the console keep working, and so the test
// suite that pins these numbers goes on pinning them from where they are used.
export {
  BYPASS_FROM_CLASS,
  QUIET_END_HOUR,
  QUIET_HOURS_CHANNELS,
  QUIET_RELEASE_HOUR,
  QUIET_START_HOUR,
  colomboHour,
  colomboParts,
  inQuietHours,
  quietHoursState,
  releaseAt,
};
export type { QuietHoursState };

export interface QuietHoursNoticeProps {
  readonly state: QuietHoursState;
  readonly locale: Locale;
  readonly className?: string;
}

/**
 * The notice.
 *
 * Rendered in every state, including "quiet hours are not in effect". An operator who only
 * ever sees this panel at night learns nothing from its absence during the day; one who
 * sees it say "not in effect" at 14:00 knows the rule exists and knows the console is
 * tracking it.
 */
export function QuietHoursNotice({ state, locale, className }: QuietHoursNoticeProps) {
  const t = useTranslations('alerts');

  return (
    <section
      data-quiet-hours={state.active ? 'active' : 'inactive'}
      data-quiet-hours-deferred={state.deferred}
      className={cn(
        'flex flex-col gap-1 rounded-[var(--radius-default)] border px-4 py-3',
        state.deferred
          ? 'border-[var(--pending)] text-[var(--pending)]'
          : 'border-[var(--divider)] text-[var(--text-muted)]',
        className,
      )}
    >
      <h2 className="text-sm font-medium">
        {state.active ? t('quietHoursActive') : t('quietHoursInactive')}
      </h2>
      {/* The rule itself, not just its outcome. An operator who can read the rule can
          predict it next time; one shown only its verdict has to re-learn it each night. */}
      <p className="text-xs">
        {t('quietHoursRule', {
          start: String(QUIET_START_HOUR).padStart(2, '0'),
          end: String(QUIET_END_HOUR).padStart(2, '0'),
          level: BYPASS_FROM_CLASS,
          channels: QUIET_HOURS_CHANNELS.join(', '),
        })}
      </p>
      <p className="text-xs">
        {state.deferred
          ? t('quietHoursDeferred', { time: formatTime(state.releaseAt, locale) })
          : state.active
            ? t('quietHoursBypass')
            : t('quietHoursNoEffect')}
      </p>
    </section>
  );
}
