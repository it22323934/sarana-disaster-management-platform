'use client';

/**
 * Quiet hours, and whether this alert bypasses them.
 *
 * Build file 20 asks that the composer show "quiet-hours state, with the rule and whether
 * this alert bypasses it". The rule itself lives in
 * `agent_svc.agents.warning.channels` and is enforced there; this is a **display** of it,
 * and the distinction matters:
 *
 * - Nothing here decides anything. The warning agent defers the SMS, and it does so
 *   whatever this component renders. If the two ever disagree the agent is right.
 * - It is duplicated for the same reason the SMS segment count is: the operator has to
 *   know *before* sending that a watch-level alert at 2am will sit until 06:00. A state
 *   they can only discover from the delivery panel the next morning is a state they find
 *   out about too late to reword or re-time the message.
 *
 * The constants are pinned to the Python ones by `quiet-hours.test.ts`, which walks the
 * clock through a full day and asserts the boundaries the Python module documents.
 *
 * **Colombo local, not UTC.** The rule is about when somebody is asleep, and Sri Lanka is
 * UTC+5:30 - a UTC hour test is off by five and a half hours, which puts the whole quiet
 * window in the wrong half of the evening. `Intl` does the conversion against the IANA
 * database rather than any arithmetic here.
 */

import { cn } from '@sarana/ui';
import { COLOMBO_TIMEZONE, formatTime } from '@sarana/ts-shared/format';
import type { Locale } from '@sarana/ts-shared/i18n';
import { useTranslations } from 'next-intl';

/** Inclusive of the start hour, exclusive of the end. Mirrors `QUIET_START_HOUR`. */
export const QUIET_START_HOUR = 22;
export const QUIET_END_HOUR = 5;

/**
 * When a deferred SMS is released.
 *
 * 06:00 rather than 05:00, an hour after quiet hours end. A message arriving the instant
 * the window closes still wakes the household that set an alarm for six.
 */
export const QUIET_RELEASE_HOUR = 6;

/**
 * At and above this class, quiet hours are bypassed.
 *
 * Mirrors `ALL_CHANNELS_FROM`. Class 3 is a warning and class 4 is the evacuate line;
 * both wake a district at night, and that bypass is the entire point of having the rule
 * written down rather than left to a duty officer's judgement at 3am.
 */
export const BYPASS_FROM_CLASS = 3;

/** The channels that go quiet. Only the ones that make a handset make a noise. */
export const QUIET_HOURS_CHANNELS = ['SMS', 'USSD', 'PUSH'] as const;

export interface QuietHoursState {
  /** Whether it is currently between 22:00 and 05:00 in Colombo. */
  readonly active: boolean;
  /** Whether this alert's severity sends anyway. */
  readonly bypasses: boolean;
  /** True when quiet hours are active and this alert does not bypass them. */
  readonly deferred: boolean;
  /** Colombo hour, 0-23. Exposed so a test can assert without stubbing the clock twice. */
  readonly colomboHour: number;
  /** When a deferred message would be released, as an instant. */
  readonly releaseAt: Date;
}

/**
 * The Colombo-local hour and minute for an instant.
 *
 * From the IANA database via `Intl` rather than by adding an offset. Sri Lanka is UTC+5:30
 * and the half hour is exactly what arithmetic gets wrong: zeroing the UTC minutes to
 * reach "the top of the hour" lands on :30 in Colombo, which is how a release computed for
 * 06:00 quietly becomes 06:30.
 */
export function colomboParts(moment: Date): { hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: COLOMBO_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(moment);
  const value = (type: string) =>
    Number(parts.find((part) => part.type === type)?.value ?? '0');
  // `en-GB` renders midnight as "24" in some ICU versions. Normalising here rather than
  // choosing a different locale, because the locale is not what this depends on.
  return { hour: value('hour') % 24, minute: value('minute') };
}

/** The Colombo-local hour for an instant. */
export function colomboHour(moment: Date): number {
  return colomboParts(moment).hour;
}

export function inQuietHours(moment: Date): boolean {
  const hour = colomboHour(moment);
  return hour >= QUIET_START_HOUR || hour < QUIET_END_HOUR;
}

/** Minutes in a day, for the wrap when 06:00 Colombo has already passed. */
const MINUTES_PER_DAY = 24 * 60;

/**
 * When a message deferred at `moment` would go out.
 *
 * 06:00 Colombo, today if it is still to come and tomorrow if it is not.
 *
 * Computed as a **minute offset from now** rather than by constructing a local date or by
 * snapping to the top of a UTC hour. A `Date` built from Colombo wall-clock parts in a
 * browser on any other timezone is a different instant; and snapping UTC minutes to zero
 * lands on :30 in Colombo, because the offset is +5:30. That second one is not
 * hypothetical - it is the bug this function had, and it turned an 06:00 release into an
 * 06:30 one, which is exactly the half hour the rule exists to protect.
 */
export function releaseAt(moment: Date): Date {
  const { hour, minute } = colomboParts(moment);
  const nowMinutes = hour * 60 + minute;
  const targetMinutes = QUIET_RELEASE_HOUR * 60;
  const delta =
    targetMinutes > nowMinutes
      ? targetMinutes - nowMinutes
      : targetMinutes - nowMinutes + MINUTES_PER_DAY;
  return new Date(moment.getTime() + delta * 60_000);
}

/**
 * The whole quiet-hours picture for one alert at one instant.
 *
 * `severity` is nullable because a draft may not carry one yet. An unknown severity does
 * **not** bypass: assuming the highest class for a message whose grade nobody has set
 * would wake a district on the strength of a missing field.
 */
export function quietHoursState(moment: Date, severity: number | null): QuietHoursState {
  const active = inQuietHours(moment);
  const bypasses = (severity ?? 0) >= BYPASS_FROM_CLASS;
  return {
    active,
    bypasses,
    deferred: active && !bypasses,
    colomboHour: colomboHour(moment),
    releaseAt: releaseAt(moment),
  };
}

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
