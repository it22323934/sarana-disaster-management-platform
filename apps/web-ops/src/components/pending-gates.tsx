'use client';

/**
 * The pending gate banner, wired to the two queues.
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
 * The escalation is `PendingGateBanner`'s, from the design system, so the operations
 * console and the field app escalate identically and the thresholds live in one place.
 */

import { Button, PendingGateBanner } from '@sarana/ui';
import { useTranslations } from 'next-intl';

import { Link } from '../i18n/routing';
import { usePendingPlans } from '../lib/queries';

export interface PendingGatesProps {
  /** Hidden on the gate screens themselves — you are already looking at the item. */
  readonly suppress?: boolean;
}

export function PendingGates({ suppress = false }: PendingGatesProps) {
  const t = useTranslations();
  const plans = usePendingPlans();

  if (suppress) return null;

  // While the first fetch is in flight, render nothing rather than a zero. A banner that
  // flashes "0 waiting" and then "3 waiting" teaches an operator that the number lags.
  if (plans.isPending || plans.isError) return null;

  const waiting = plans.data ?? [];
  if (waiting.length === 0) return null;

  const oldest = waiting[0];
  if (!oldest) return null;

  return (
    <div className="px-4 pt-3">
      <PendingGateBanner
        kind="dispatch"
        count={waiting.length}
        oldestWaitingSince={oldest.proposed_at}
        title={(count) => t('gate.dispatchTitle', { count })}
        ageLabel={(seconds) =>
          seconds < 60
            ? t('gate.ageSeconds', { seconds })
            : t('gate.age', { minutes: Math.round(seconds / 60) })
        }
        action={
          <Button asChild variant="primary" size="sm">
            <Link href="/ops/dispatch">{t('gate.openQueue')}</Link>
          </Button>
        }
        // `onEnableSound` is deliberately not passed. The banner offers the sound control
        // only when a handler is given, and there is no alert sound yet — offering a
        // control that does nothing is worse than not offering it, because an operator who
        // enables it then believes they will be told. The string is translated and ready;
        // wiring it is named in the handoff.
      />
    </div>
  );
}
