'use client';

/**
 * The pending gate banner, wired to **both** queues.
 *
 * This is the most important element on the console. SARANA has exactly two mandatory
 * human gates — committing a life-safety dispatch, and releasing a disbursement — and no
 * flag anywhere bypasses either. A gate nobody notices is a queue, not a gate, so this
 * sits above every operational page and is not dismissible while anything is waiting.
 *
 * It escalates on the age of the **oldest** waiting item, not on the count. A count-led
 * banner lets one very old item hide behind a quiet afternoon; the question a gate has to
 * answer is "what has been waiting longest", because that is the item whose delay is
 * doing damage.
 *
 * **Both gates are counted, and they are counted separately.** The banner used to show
 * dispatches only, because nothing could list entitlements awaiting release — so it
 * under-reported, silently, on the half of the platform that moves money. `GET /entitlements`
 * closed that. They stay two banners rather than one summed count: "3 waiting" spanning a
 * dispatch and two releases tells a dispatcher nothing about whether any of it is theirs,
 * and the two go to different people.
 *
 * **The sound is real now.** `PendingGateBanner` offers the control only when a handler is
 * passed, and passing one that did nothing would be worse than passing none — an operator
 * who enables it then believes they will be told. The handler here plays a short tone
 * through the Web Audio API, which needs no asset and no network, and it can only be armed
 * by a click, which is also what browsers require before audio may play at all.
 */

import { Button, PendingGateBanner } from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { Link } from '../i18n/routing';
import { useEntitlementQueue, usePendingPlans } from '../lib/queries';

export interface PendingGatesProps {
  /** Hidden on the gate screens themselves — you are already looking at the item. */
  readonly suppress?: boolean;
}

export function PendingGates({ suppress = false }: PendingGatesProps) {
  const t = useTranslations();
  const plans = usePendingPlans();
  // Everything the approval rule says is ready for a person to release. The service
  // applies that rule, not the console: a second copy of it here is a second copy that can
  // drift, and the way drift presents is a banner offering work the gate then refuses.
  const releases = useEntitlementQueue(true);

  const { armed, arm, announce } = useGateSound();

  const waitingPlans = plans.isPending || plans.isError ? [] : (plans.data ?? []);
  const waitingReleases = releases.isPending || releases.isError ? [] : (releases.data ?? []);

  // Ring once when something new arrives, never on a re-render and never on the first
  // load. A tone on mount would fire every navigation and be switched off within an hour.
  const total = waitingPlans.length + waitingReleases.length;
  const previousTotal = useRef<number | null>(null);
  useEffect(() => {
    if (previousTotal.current !== null && total > previousTotal.current) announce();
    previousTotal.current = total;
  }, [total, announce]);

  if (suppress) return null;
  if (total === 0) return null;

  const oldestPlan = waitingPlans[0];
  // Oldest first, from the server. `calculated_at` is when the entitlement became work,
  // which is the clock an approver is judged against.
  const oldestRelease = waitingReleases[0];

  return (
    <div className="flex flex-col gap-2 px-4 pt-3">
      {oldestPlan ? (
        <PendingGateBanner
          kind="dispatch"
          count={waitingPlans.length}
          oldestWaitingSince={oldestPlan.proposed_at}
          title={(count) => t('gate.dispatchTitle', { count })}
          ageLabel={ageLabel(t)}
          onEnableSound={armed ? undefined : arm}
          soundLabel={t('gate.enableSound')}
          action={
            <Button asChild variant="primary" size="sm">
              <Link href="/ops/dispatch">{t('gate.openQueue')}</Link>
            </Button>
          }
        />
      ) : null}

      {oldestRelease ? (
        <PendingGateBanner
          kind="disbursement"
          count={waitingReleases.length}
          oldestWaitingSince={oldestRelease.calculated_at}
          title={(count) => t('gate.disbursementTitle', { count })}
          ageLabel={ageLabel(t)}
          onEnableSound={armed ? undefined : arm}
          soundLabel={t('gate.enableSound')}
          action={
            <Button asChild variant="primary" size="sm">
              <Link href="/disbursements">{t('gate.openQueue')}</Link>
            </Button>
          }
        />
      ) : null}
    </div>
  );
}

/** Seconds under a minute read as seconds. "Waiting 0 min" is worse than "waiting 40 s". */
function ageLabel(t: ReturnType<typeof useTranslations>) {
  return (seconds: number) =>
    seconds < 60
      ? t('gate.ageSeconds', { seconds })
      : t('gate.age', { minutes: Math.round(seconds / 60) });
}

/**
 * A short tone, played from the Web Audio API.
 *
 * No asset and no network: an operations room on a degraded connection is exactly when
 * this must work, and a missing mp3 would fail in the one condition it exists for.
 *
 * Arming is a click, which is not only a design choice — browsers refuse to start an audio
 * context without a user gesture, so a banner that armed itself would be silent and would
 * *look* armed, which is the failure mode this whole component is written against.
 *
 * Two notes, not one. A single beep is indistinguishable from a notification from any
 * other application on the machine; a rising pair is recognisable as this console's.
 */
function useGateSound(): {
  armed: boolean;
  arm: () => void;
  announce: () => void;
} {
  const [armed, setArmed] = useState(false);
  const contextRef = useRef<AudioContext | null>(null);

  const arm = useCallback(() => {
    try {
      const Ctor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return;
      contextRef.current = new Ctor();
      setArmed(true);
    } catch {
      // No audio device, a browser that refuses, or a locked-down kiosk. The banner keeps
      // offering the control rather than claiming it is on, because a control that says
      // "sound enabled" and makes no sound is the thing this must never do.
    }
  }, []);

  const announce = useCallback(() => {
    const context = contextRef.current;
    if (!context) return;
    try {
      const now = context.currentTime;
      for (const [index, frequency] of [660, 880].entries()) {
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.type = 'sine';
        oscillator.frequency.value = frequency;
        // Ramped rather than switched. A square-edged gate on an oscillator clicks, and a
        // click in an operations room reads as a fault rather than as a notification.
        const start = now + index * 0.18;
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.2, start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.16);
        oscillator.connect(gain).connect(context.destination);
        oscillator.start(start);
        oscillator.stop(start + 0.18);
      }
    } catch {
      // A context suspended by the browser after a tab moved to the background. Silence is
      // the correct outcome; the banner itself is still escalating on screen.
    }
  }, []);

  useEffect(() => () => void contextRef.current?.close(), []);

  return { armed, arm, announce };
}
