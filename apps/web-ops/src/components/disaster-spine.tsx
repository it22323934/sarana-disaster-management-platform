'use client';

/**
 * The time spine, wired to the active hazard event.
 *
 * Everything in SARANA is anchored to a disaster clock, and until `GET /hazard-events`
 * existed the console had nothing to anchor to — so the signature element of the design
 * system sat in Storybook and on no screen.
 *
 * **It renders nothing when there is no landfall.** An event under monitoring has no T+0,
 * and a spine drawn from the declaration time instead would put a fabricated landfall
 * across the top of every operational screen. Absent is the honest state between events,
 * and it is also the common one.
 *
 * **The milestones are the ones the platform can actually date.** The brief lists forecast
 * issued, alert dispatched, first incident, peak queue depth and first disbursement. Only
 * the event's own declaration and landfall are readable today; the rest need queries that
 * do not exist. Showing three hollow markers labelled with things that have not been
 * measured would be worse than showing the two that are real.
 */

import { TimeSpine } from '@sarana/ui';
import type { SpineMilestone } from '@sarana/ui';
import { localised, type Locale } from '@sarana/ts-shared/i18n';
import { useTranslations } from 'next-intl';

import { useHazardEvents } from '../lib/queries';
import { anchorEvent } from '../lib/schemas';

export interface DisasterSpineProps {
  readonly locale: Locale;
  /** Collapsed to a single line. The mobile form, and the form on a dense screen. */
  readonly compact?: boolean;
}

export function DisasterSpine({ locale, compact = false }: DisasterSpineProps) {
  const t = useTranslations('spine');
  const events = useHazardEvents();

  const event = anchorEvent(events.data ?? []);
  // No event, or none with a landfall. Nothing to anchor to, so nothing is drawn.
  if (!event?.landfall_at) return null;

  const milestones: SpineMilestone[] = [];
  if (event.declared_at) {
    milestones.push({ id: 'declared', at: event.declared_at, label: t('declared') });
  }

  return (
    <TimeSpine
      landfall={event.landfall_at}
      // The real clock. The spine is the one element that must never be pinned to a
      // fixture: an operator reads their position on it, and a frozen "you are here" is
      // worse than no rail at all.
      now={new Date().toISOString()}
      locale={locale}
      compact={compact}
      label={`${t('label')}: ${localised(event.name, locale)}`}
      nowLabel={t('youAreHere')}
      phaseLabel={t(phaseForOffsetHours(offsetHours(event.landfall_at)))}
      milestones={milestones}
    />
  );
}

/** Hours since landfall. Negative before it. */
export function offsetHours(landfallIso: string, now: Date = new Date()): number {
  return (now.getTime() - new Date(landfallIso).getTime()) / 3_600_000;
}

/**
 * Which phase the present sits in, from the offset alone.
 *
 * Boundaries taken from how the response is actually run rather than from a model: the
 * first seventy-two hours after landfall are the response, and after that the work is
 * recovery. Before landfall it is anticipatory action, which is the window the whole
 * forecasting half of this platform exists to open.
 *
 * Returns a message key, not a label. The caller translates it, so the phase is never an
 * English word on a Tamil console.
 */
export function phaseForOffsetHours(
  hours: number,
): 'anticipatory' | 'response' | 'recovery' {
  if (hours < 0) return 'anticipatory';
  if (hours < 72) return 'response';
  return 'recovery';
}
