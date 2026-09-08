/**
 * Whether a notification is allowed to make this handset make a noise.
 *
 * Two rules, and the second one is the reason this file is not just a settings read.
 *
 * **An evacuation order is not a notification preference.** At `impact_class >= 3` the
 * alert delivers whatever the user has muted, and it bypasses quiet hours. Someone who
 * turned off flood watches in June is not thereby someone who declined an evacuation
 * order in November, and treating those as the same choice would be reading a preference
 * as consent to not be warned.
 *
 * **Below class 3, the user's settings and quiet hours both apply.** A watch-level alert
 * at 2am wakes a district for something that will still be true at six, and the rule for
 * that is the same one the warning agent enforces server-side - imported from
 * `@sarana/ts-shared/domain` rather than re-derived, because the last mirror of it
 * shipped with a half-hour timezone bug.
 */

import { BYPASS_FROM_CLASS, inQuietHours, releaseAt } from '@sarana/ts-shared/domain';

export type NotificationKind =
  | 'alert'
  | 'report-status'
  | 'disbursement-released'
  | 'grievance-updated';

export interface NotificationPreferences {
  /**
   * The lowest alert class the user wants to hear about.
   *
   * 0 means everything. Anything above `BYPASS_FROM_CLASS` is stored as given and
   * ignored where it would suppress a class 3 or 4 - the setting is honoured as far as it
   * can be and no further, and the settings screen says so in words rather than by
   * silently clamping the control.
   */
  readonly minimumAlertClass: number;
  /** Money and case updates. These are never life-safety and are fully the user's call. */
  readonly aidUpdates: boolean;
  readonly reportUpdates: boolean;
}

export const DEFAULT_PREFERENCES: NotificationPreferences = {
  minimumAlertClass: 1,
  aidUpdates: true,
  reportUpdates: true,
};

export interface NotificationRequest {
  readonly kind: NotificationKind;
  /** The alert's impact class, 0-4. Null for anything that is not an alert. */
  readonly impactClass: number | null;
  readonly at: Date;
  readonly preferences: NotificationPreferences;
}

export type NotificationDecision =
  | { readonly deliver: 'now'; readonly bypassedMute: boolean; readonly bypassedQuietHours: boolean }
  | { readonly deliver: 'deferred'; readonly until: Date; readonly reason: 'quiet-hours' }
  | { readonly deliver: 'never'; readonly reason: 'muted-by-preference' };

export function decideNotification(request: NotificationRequest): NotificationDecision {
  const { kind, impactClass, at, preferences } = request;

  if (kind === 'alert') {
    const level = impactClass ?? 0;

    if (level >= BYPASS_FROM_CLASS) {
      // Class 3 is a warning and class 4 is the evacuate line. Both wake a district at
      // night, and that bypass is the entire point of writing the rule down rather than
      // leaving it to a duty officer's judgement at 3am.
      return {
        deliver: 'now',
        bypassedMute: level < preferences.minimumAlertClass,
        bypassedQuietHours: inQuietHours(at),
      };
    }

    if (level < preferences.minimumAlertClass) {
      return { deliver: 'never', reason: 'muted-by-preference' };
    }

    if (inQuietHours(at)) {
      return { deliver: 'deferred', until: releaseAt(at), reason: 'quiet-hours' };
    }

    return { deliver: 'now', bypassedMute: false, bypassedQuietHours: false };
  }

  const wanted =
    kind === 'report-status' ? preferences.reportUpdates : preferences.aidUpdates;
  if (!wanted) return { deliver: 'never', reason: 'muted-by-preference' };

  // A disbursement release at 2am is good news that keeps until morning. None of these is
  // ever life-safety, so quiet hours apply to all of them without exception.
  if (inQuietHours(at)) {
    return { deliver: 'deferred', until: releaseAt(at), reason: 'quiet-hours' };
  }
  return { deliver: 'now', bypassedMute: false, bypassedQuietHours: false };
}

/**
 * The lowest class a user may actually mute.
 *
 * Exposed so the settings screen can show the control stopping where the rule does,
 * with an explanation, rather than accepting a value it will then ignore.
 */
export const HIGHEST_MUTABLE_CLASS = BYPASS_FROM_CLASS - 1;
