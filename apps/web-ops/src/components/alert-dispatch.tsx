'use client';

/**
 * `/ops/alerts/[id]` — the draft, the mandatory dry run, and the send.
 *
 * The composer creates a draft and stops. This screen is the other half, and the gap
 * between them is deliberate: one button that drafted and sent is how a national fan-out
 * happens by accident.
 *
 * **The dry run is mandatory and the console enforces it before the server does.** Send is
 * unreachable until a dry run has been performed *for the current state of this alert*.
 * `alerting-svc` would happily accept a dispatch without one — the dry run takes no
 * transport at all, so nothing server-side knows whether anybody looked. That makes this
 * the only place the rule can live, and it is why the result is cleared rather than kept:
 * a stale count from ten minutes ago is worse than no count, because it looks like
 * diligence.
 *
 * **The cap is the server's number, not a comparison made here.** `exceeds_cap` and `cap`
 * come back in the dry run. Recomputing the comparison in the browser would be a second
 * copy of a threshold that exists to stop twenty million messages, and the two copies
 * would eventually disagree in the direction that lets the send through.
 *
 * **An override needs a typed reason, and the reason goes to the server.** `alerting-svc`
 * refuses `override_cap` without one. The console makes the button unreachable without it
 * so the refusal never happens, which is the same pattern as the anomaly disposition note.
 *
 * **Quiet hours are shown with the rule and whether this alert bypasses it.** Between
 * 22:00 and 05:00 Colombo, only impact class 3 and above wakes a district by SMS. An
 * operator sending a watch-level alert at 2am has to know it will be queued to 06:00
 * rather than discovering it from the delivery panel the next morning.
 */

import {
  Badge,
  Button,
  DialogContent,
  DialogRoot,
  DialogTrigger,
  EmptyState,
  ReferenceCode,
  RelativeTime,
  SeverityPill,
  Skeleton,
  Textarea,
  cn,
} from '@sarana/ui';
import type { SeverityLevel } from '@sarana/ui';
import { LOCALE_NAMES, type Locale } from '@sarana/ts-shared/i18n';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { Link } from '../i18n/routing';
import { gatewayFetch } from '../lib/gateway-client';
import { dryRunAlert, useAlert, useInvalidateGates } from '../lib/queries';
import { dispatchResultSchema, type DryRun } from '../lib/schemas';
import { ErrorPanel } from './degraded';
import { QuietHoursNotice, quietHoursState } from './quiet-hours';

/** Statuses from which a dispatch is still possible. Anything else is already decided. */
const DISPATCHABLE_STATUSES = ['DRAFT', 'PENDING_SIGNOFF', 'APPROVED'];

export interface AlertDispatchProps {
  readonly alertId: string;
}

export function AlertDispatch({ alertId }: AlertDispatchProps) {
  const t = useTranslations('alerts');
  const common = useTranslations('common');
  const compose = useTranslations('compose');
  const locale = useLocale() as Locale;

  const alert = useAlert(alertId);
  const invalidate = useInvalidateGates();

  const [plan, setPlan] = useState<DryRun | null>(null);
  const [overrideReason, setOverrideReason] = useState('');
  const [busy, setBusy] = useState<'dry-run' | 'signoff' | 'send' | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const [failure, setFailure] = useState<unknown>(null);

  async function runDryRun(): Promise<void> {
    setBusy('dry-run');
    setFailure(null);
    // Cleared before the call, not after. A previous plan sitting on screen while a new
    // one is in flight lets an operator read a count that is about to be replaced.
    setPlan(null);
    try {
      setPlan(await dryRunAlert(alertId));
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(null);
    }
  }

  async function signOff(): Promise<void> {
    setBusy('signoff');
    setFailure(null);
    try {
      await gatewayFetch(`alerts/${alertId}/signoff`, {
        method: 'POST',
        body: {},
        idempotencyKey: `signoff-${alertId}`,
      });
      await alert.refetch();
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(null);
    }
  }

  async function send(): Promise<void> {
    if (!plan) return;
    setBusy('send');
    setFailure(null);
    try {
      const result = await gatewayFetch(`alerts/${alertId}/dispatch`, {
        method: 'POST',
        body: {
          dry_run: false,
          override_cap: plan.exceeds_cap,
          override_reason: plan.exceeds_cap ? overrideReason.trim() : null,
        },
        // Keyed on the alert, so a double-tap replays the stored response rather than
        // fanning out twice. This is the single most expensive button in the product.
        idempotencyKey: `dispatch-${alertId}`,
        schema: dispatchResultSchema,
      });
      setSent(result.summary);
      // The plan described a state that no longer exists: the alert has been sent.
      setPlan(null);
      await Promise.all([alert.refetch(), invalidate()]);
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(null);
    }
  }

  if (alert.isPending) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (alert.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={alert.error}>
          <Button asChild variant="secondary" size="sm" className="mt-2 self-start">
            <Link href="/ops/alerts">{t('title')}</Link>
          </Button>
        </ErrorPanel>
      </div>
    );
  }

  const record = alert.data;
  const dispatchable = DISPATCHABLE_STATUSES.includes(record.status);
  const awaitingSignoff = record.requires_human_signoff && record.status === 'PENDING_SIGNOFF';
  const quiet = quietHoursState(new Date(), record.severity);
  const overrideNeeded = plan?.exceeds_cap ?? false;
  const canSend =
    dispatchable &&
    !awaitingSignoff &&
    plan !== null &&
    (!overrideNeeded || overrideReason.trim().length >= 3) &&
    busy === null;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{t('draftTitle')}</h1>
        <ReferenceCode code={record.cap_identifier} kind={t('capId')} />
        {record.severity !== null ? (
          <SeverityPill level={record.severity as SeverityLevel} locale="en" />
        ) : null}
        <Badge tone={record.requires_human_signoff ? 'pending' : 'neutral'}>{record.status}</Badge>
        {record.created_at ? (
          <span className="ml-auto text-xs text-[var(--text-muted)]">
            <RelativeTime value={record.created_at} />
          </span>
        ) : null}
      </header>

      <QuietHoursNotice state={quiet} locale={locale} />

      {/* Free text forces a named human to sign before anything can be dispatched. Shown
          as a blocking state rather than as a note: the send button below is unreachable
          until it clears, and an operator should learn that here rather than at the
          bottom of the screen. */}
      {awaitingSignoff ? (
        <section className="flex flex-col gap-2 rounded-[var(--radius-default)] border-2 border-[var(--pending)] px-4 py-3">
          <h2 className="text-sm font-medium text-[var(--pending)]">{t('signoffRequired')}</h2>
          <p className="text-xs text-[var(--text-muted)]">{t('signoffHint')}</p>
          <Button
            variant="secondary"
            size="sm"
            className="self-start"
            busy={busy === 'signoff'}
            busyLabel={t('signOff')}
            disabled={busy !== null}
            onClick={signOff}
          >
            {t('signOff')}
          </Button>
        </section>
      ) : null}

      <section className="flex flex-col gap-3 rounded-[var(--radius-default)] border border-[var(--divider)] p-4">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="text-sm font-medium">{t('dryRun')}</h2>
          <p className="text-xs text-[var(--text-muted)]">{t('dryRunHint')}</p>
        </div>

        <Button
          variant={plan === null ? 'primary' : 'secondary'}
          size="lg"
          className="self-start"
          disabled={!dispatchable || busy !== null}
          busy={busy === 'dry-run'}
          busyLabel={t('runDryRun')}
          onClick={runDryRun}
        >
          {plan === null ? t('runDryRun') : t('runDryRunAgain')}
        </Button>

        {plan ? <DryRunResult plan={plan} /> : <p className="text-xs">{t('dryRunFirst')}</p>}
      </section>

      {overrideNeeded ? (
        <section className="flex flex-col gap-2 rounded-[var(--radius-default)] border-2 border-[var(--sev-3-border)] bg-[var(--sev-3-bg)] px-4 py-3 text-[var(--sev-3-fg)]">
          <h2 className="text-sm font-semibold">
            {t('exceedsCap', { targeted: plan?.targeted ?? 0, cap: plan?.cap ?? 0 })}
          </h2>
          <p className="text-xs opacity-90">{t('exceedsCapHint')}</p>
          {/* A typed reason, not a checkbox. The server refuses an override without one,
              and a checkbox is a thing a hand ticks; a sentence is a thing somebody has to
              mean. It is stored with the dispatch and read afterwards. */}
          <Textarea
            label={t('overrideReason')}
            description={t('overrideReasonHint')}
            required
            value={overrideReason}
            onChange={(event) => setOverrideReason(event.target.value)}
            maxLength={500}
          />
        </section>
      ) : null}

      {failure ? <ErrorPanel error={failure} /> : null}

      {sent ? (
        <EmptyState
          title={t('sent')}
          description={sent}
          action={
            <Button asChild variant="secondary">
              <Link href={`/ops/alerts/${alertId}/delivery`}>{t('deliveryTitle')}</Link>
            </Button>
          }
        />
      ) : !dispatchable ? (
        <EmptyState title={record.status} description={t('notDispatchable')} />
      ) : (
        <section className="flex flex-col gap-3">
          <DialogRoot>
            <DialogTrigger asChild>
              <Button variant="primary" size="lg" disabled={!canSend} className="self-start">
                {t('send')}
              </Button>
            </DialogTrigger>
            {/* A confirmation that restates the count rather than asking "are you sure".
                The number is the decision, and a dialogue that does not repeat it is a
                dialogue people click through. */}
            <DialogContent title={t('sendConfirmTitle')} description={t('sendConfirmBody')}>
              <div className="flex flex-col gap-4">
                {plan ? <DryRunResult plan={plan} compact /> : null}
                <p className="text-xs text-[var(--text-muted)]">{compose('dryRunExplanation')}</p>
                <Button
                  variant="primary"
                  size="lg"
                  busy={busy === 'send'}
                  busyLabel={t('send')}
                  disabled={!canSend}
                  onClick={send}
                >
                  {t('sendNow')}
                </Button>
              </div>
            </DialogContent>
          </DialogRoot>

          {plan === null ? (
            <p className="text-xs text-[var(--sev-2-fg)]">{t('sendBlockedByDryRun')}</p>
          ) : null}
          {overrideNeeded && overrideReason.trim().length < 3 ? (
            <p className="text-xs text-[var(--sev-3-fg)]">{t('sendBlockedByOverride')}</p>
          ) : null}
          <p className="text-2xs text-[var(--text-muted)]">{common('review')}</p>
        </section>
      )}
    </div>
  );
}

/**
 * What the dry run says this alert would do.
 *
 * Every figure is a count with its own denominator or a total in its own right; there is
 * no percentage anywhere, for the same reason there is none on the delivery panel. The
 * cost is marked indicative because it is: `COST_PER_MESSAGE_LKR` is a per-message
 * estimate, not a tariff, and presenting it as an invoice would be a number somebody
 * quotes in a meeting.
 */
function DryRunResult({ plan, compact = false }: { readonly plan: DryRun; readonly compact?: boolean }) {
  const t = useTranslations('alerts');

  return (
    <div data-dry-run-targeted={plan.targeted} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
        <Figure label={t('targeted')} value={plan.targeted.toLocaleString('en-LK')} />
        <Figure
          label={t('estimatedCost')}
          value={`Rs. ${plan.estimated_cost_lkr.toLocaleString('en-LK', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}`}
          hint={t('estimatedCostHint')}
        />
        <Figure
          label={t('cap')}
          value={plan.cap.toLocaleString('en-LK')}
          hint={plan.exceeds_cap ? t('overCap') : t('underCap')}
        />
      </div>

      {compact ? null : (
        <div className="grid gap-4 sm:grid-cols-2">
          <Breakdown
            title={t('byChannel')}
            rows={Object.entries(plan.by_channel).map(([channel, count]) => ({
              label: channel,
              value: count.toLocaleString('en-LK'),
            }))}
          />
          <Breakdown
            title={t('byLanguage')}
            rows={Object.entries(plan.by_language).map(([language, count]) => ({
              // The language's own name, so a per-language split is readable by the person
              // it is about rather than only by an English reader.
              label: LOCALE_NAMES[language as Locale] ?? language,
              value: count.toLocaleString('en-LK'),
            }))}
          />
        </div>
      )}
    </div>
  );
}

function Figure({
  label,
  value,
  hint,
}: {
  readonly label: string;
  readonly value: string;
  readonly hint?: string;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">{label}</span>
      <span data-sarana-datum="" className="font-mono text-lg font-semibold">
        {value}
      </span>
      {hint ? <span className="text-2xs text-[var(--text-muted)]">{hint}</span> : null}
    </div>
  );
}

function Breakdown({
  title,
  rows,
}: {
  readonly title: string;
  readonly rows: ReadonlyArray<{ readonly label: string; readonly value: string }>;
}) {
  return (
    <section
      className={cn(
        'rounded-[var(--radius-default)] border border-[var(--divider)]',
        'bg-[var(--surface-card)] p-3',
      )}
    >
      <h3 className="mb-2 text-xs font-medium">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-xs text-[var(--text-muted)]">—</p>
      ) : (
        <dl className="flex flex-col gap-1">
          {rows.map((row) => (
            <div key={row.label} className="flex items-baseline justify-between gap-4 text-xs">
              <dt className="text-[var(--text-muted)]">{row.label}</dt>
              <dd data-sarana-datum="" className="font-mono">
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

/** Re-exported so the a11y sweep and the e2e suite can render the panel in isolation. */
export { DryRunResult };
