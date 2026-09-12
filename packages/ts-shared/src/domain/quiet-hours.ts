/**
 * Quiet hours: when a handset is allowed to make a noise, and what overrides that.
 *
 * The rule itself lives in `agent_svc.agents.warning.channels` and is enforced there.
 * This is a **mirror** of it, and it exists because two surfaces need to know the answer
 * before the server does: the ops console has to tell an operator that a watch-level
 * alert composed at 2am will sit until 06:00, and the mobile app has to decide whether a
 * push wakes somebody. If either ever disagrees with the agent, the agent is right.
 *
 * It lives here rather than in one of the apps because there is no third copy that would
 * stay correct. The last mirror of this rule shipped with a half-hour bug - a release
 * computed by zeroing UTC minutes lands on 06:30 in Colombo, not 06:00 - and the way to
 * not have that bug twice is to not have the code twice.
 *
 * **Colombo local, not UTC.** The rule is about when somebody is asleep, and Sri Lanka is
 * UTC+5:30. `Intl` does the conversion against the IANA database rather than arithmetic.
 */

import { COLOMBO_TIMEZONE } from '../format/datetime.js';

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
