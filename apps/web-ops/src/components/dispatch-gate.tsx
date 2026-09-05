'use client';

/**
 * The dispatch gate screen. The entire safety argument, made visible.
 *
 * Layout order is the decision order, and it is not negotiable:
 *
 *   1. what is being committed — above the fold, no scrolling to see it
 *   2. the incidents, ranked, with the reasoning **expanded**
 *   3. what the plan does *not* cover
 *   4. approve and reject, side by side, equal weight
 *
 * Three rules this screen holds that are easy to lose in a redesign:
 *
 * **The reasoning is not behind a disclosure.** If the operator has to click to see why
 * incident 3 outranks incident 4, they will stop looking at it by hour six, and the gate
 * becomes a button rather than a decision.
 *
 * **Rejecting is exactly as fast as approving.** Both are one control away, both are the
 * same size, neither is pre-selected. If rejecting is slower, people approve to save
 * time, and the gate becomes theatre.
 *
 * **Approve cannot be reached by pressing Enter.** The TOTP field is focused on load so
 * an easy decision is fast, but the form does not submit on Enter and the approve button
 * stays disabled until six digits are present. A dispatcher resting a hand on the keyboard
 * must not be able to send responders towards a hazard.
 *
 * **`unservable` is above the decision, not below it.** It is often the most
 * decision-relevant thing on the page: the incident nobody can reach is the one that gets
 * escalated to a different agency, and a plan that showed only what it proposed would let
 * somebody approve while a household they never saw was left waiting.
 *
 * The reasoning is read from the plan's own `route` column rather than from the agent's
 * live interrupt payload, so it is still there for a plan whose thread was checkpointed
 * away hours ago. When the column is empty the screen says nothing recorded a reason -
 * which is a different and weaker claim than an empty factor list under a "why" heading,
 * and the difference is why `reasoning` is nullable rather than defaulted.
 */

import {
  Badge,
  Button,
  DialogContent,
  DialogRoot,
  DialogTrigger,
  EmptyState,
  Input,
  RadioGroup,
  ReferenceCode,
  RelativeTime,
  SeverityPill,
  Skeleton,
  Textarea,
  cn,
} from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import { Link } from '../i18n/routing';
import { gatewayFetch } from '../lib/gateway-client';
import { usePlan, usePlanIncidents, useInvalidateGates, useResponders } from '../lib/queries';
import {
  REJECTION_REASONS,
  decisionResponseSchema,
  type Incident,
  type IncidentFactors,
  type PlanReasoning,
  type RejectionReason,
  type Responder,
  type Unservable,
} from '../lib/schemas';
import { RouteMap } from './route-map';
import { stepUp } from '../lib/auth-actions';
import { DegradedBanner, ErrorPanel } from './degraded';

const TOTP_LENGTH = 6;

export interface DispatchGateProps {
  readonly planId: string;
}

export function DispatchGate({ planId }: DispatchGateProps) {
  const t = useTranslations('dispatch');
  const common = useTranslations('common');
  const reasons = useTranslations('rejectionReason');
  const errors = useTranslations('errors');
  const gate = useTranslations('gate');
  const cop = useTranslations('cop');

  const plan = usePlan(planId);
  const incidents = usePlanIncidents(plan.data?.incident_ids ?? []);
  const responders = useResponders();
  const invalidate = useInvalidateGates();

  const [totp, setTotp] = useState('');
  const [reason, setReason] = useState<RejectionReason>('INCORRECT_PRIORITISATION');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const totpRef = useRef<HTMLInputElement>(null);

  // Focused on load so approving is fast when the decision is easy. It is the only
  // autofocus on the screen: focus is a scarce signal and it belongs on the thing that
  // gates the action.
  useEffect(() => {
    if (plan.data && !plan.isPending) totpRef.current?.focus();
  }, [plan.data, plan.isPending]);

  const totpComplete = /^\d{6}$/.test(totp);

  /**
   * The idempotency key is stable for this plan and this operator's attempt.
   *
   * Regenerating it per click would let a double-tap become two dispatches. Keying it on
   * the plan means a retry after a network failure replays the stored response instead.
   */
  const idempotencyKey = `dispatch-approve-${planId}`;

  async function approve(): Promise<void> {
    setBusy('approve');
    setFailure(null);
    try {
      // Step up first. The service checks it again — this is not the gate, it is the
      // console collecting the second factor before making a call it knows needs one.
      const stepped = await stepUp(totp);
      if (!stepped.ok) {
        setFailure(new Error(stepped.message ?? errors('stepUpRequired')));
        return;
      }
      await gatewayFetch(`dispatch-plans/${planId}/approve`, {
        method: 'POST',
        body: { acknowledged: true },
        idempotencyKey,
        schema: decisionResponseSchema,
      });
      setTotp('');
      await Promise.all([plan.refetch(), invalidate()]);
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(null);
    }
  }

  async function reject(): Promise<void> {
    setBusy('reject');
    setFailure(null);
    try {
      await gatewayFetch(`dispatch-plans/${planId}/reject`, {
        method: 'POST',
        body: { reason, note: note.trim() === '' ? null : note.trim() },
        idempotencyKey: `dispatch-reject-${planId}`,
        schema: decisionResponseSchema,
      });
      await Promise.all([plan.refetch(), invalidate()]);
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(null);
    }
  }

  if (plan.isPending) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (plan.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={plan.error}>
          <Button asChild variant="secondary" size="sm" className="mt-2 self-start">
            <Link href="/ops/dispatch">{t('queueTitle')}</Link>
          </Button>
        </ErrorPanel>
      </div>
    );
  }

  const decided = plan.data.status !== 'PROPOSED' && plan.data.status !== 'AWAITING_SIGNOFF';
  const responderById = new Map((responders.data ?? []).map((r) => [r.id, r]));

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">{t('title')}</h1>
        <ReferenceCode code={plan.data.id.slice(0, 8)} kind={t('status')} />
        <Badge tone={decided ? 'neutral' : 'pending'}>{plan.data.status}</Badge>
        <span className="ml-auto text-xs text-[var(--text-muted)]">
          {t('proposedBy')} <span className="font-mono">{plan.data.proposed_by_agent}</span>
        </span>
      </header>

      {/* `waiting_since` is prominent, not buried. It is the number that says how much
          this delay has already cost. */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-[var(--radius-default)] border border-[var(--pending)] px-4 py-3">
        <Committing
          label={t('incidents')}
          value={String(plan.data.incident_ids.length)}
        />
        <Committing
          label={t('responders')}
          value={String(plan.data.responder_ids.length)}
        />
        <Committing
          label={cop('peopleAtRisk')}
          value={String(
            (incidents.data ?? []).reduce((total, incident) => total + incident.people_at_risk, 0),
          )}
        />
        <Committing
          label={t('estimatedDuration')}
          value={
            plan.data.estimated_duration_min === null
              ? '—'
              : t('minutes', { count: plan.data.estimated_duration_min })
          }
        />
        <div className="ml-auto flex flex-col items-end">
          <span className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {gate('waitingSince')}
          </span>
          <RelativeTime value={plan.data.proposed_at} />
        </div>
      </div>

      {/*
        The reasoning the brief requires — the per-incident factor breakdown and the
        `unservable` list — lives in the triage agent's interrupt payload, and
        `GET /dispatch-plans/{id}` does not carry it. Rather than render an empty section
        that reads as "there were no factors", the screen says what is missing and what to
        do about it. This is the honest state of the platform today: the triage agent has
        no adapters, so no plan carries a reasoning thread.
      */}
      <DegradedBanner kind="reasoning" />

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('incidents')}</h2>
        {incidents.isPending ? (
          <Skeleton className="h-32" />
        ) : incidents.isError ? (
          <ErrorPanel error={incidents.error} />
        ) : (
          <ul className="flex flex-col gap-2">
            {(incidents.data ?? []).map((incident) => (
              <IncidentRow key={incident.id} incident={incident} />
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('responders')}</h2>
        <ul className="flex flex-wrap gap-2">
          {plan.data.responder_ids.map((id) => {
            const responder = responderById.get(id);
            return (
              <li key={id}>
                <Badge tone="neutral">
                  <span className="font-mono">{responder?.callsign ?? id.slice(0, 8)}</span>
                  {responder ? ` · ${responder.type}` : null}
                </Badge>
              </li>
            );
          })}
          {plan.data.responder_ids.length === 0 ? (
            <li className="text-xs text-[var(--text-muted)]">—</li>
          ) : null}
        </ul>
      </section>

      {failure ? <ErrorPanel error={failure} /> : null}

      {decided ? (
        <EmptyState
          title={plan.data.status}
          description={
            plan.data.rejection_reason
              ? reasons(plan.data.rejection_reason as RejectionReason)
              : t('approveConfirm')
          }
          action={
            <Button asChild variant="secondary">
              <Link href="/ops/dispatch">{t('queueTitle')}</Link>
            </Button>
          }
        />
      ) : (
        <section
          aria-label={t('title')}
          className="grid gap-4 rounded-[var(--radius-default)] border border-[var(--divider)] p-4 md:grid-cols-2"
        >
          {/* Approve. The TOTP field is inside the same column so the relationship
              between the code and the action is spatial, not remembered. */}
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              // The form never submits on Enter. Approving sends people towards a hazard
              // and must be a deliberate press of a button that says so.
              event.preventDefault();
            }}
          >
            <Input
              ref={totpRef}
              label={t('totpLabel')}
              description={t('totpHint')}
              value={totp}
              onChange={(event) => setTotp(event.target.value.replace(/\D/g, '').slice(0, TOTP_LENGTH))}
              inputMode="numeric"
              autoComplete="one-time-code"
              datum
              maxLength={TOTP_LENGTH}
              error={totp.length > 0 && !totpComplete ? t('totpIncomplete') : undefined}
            />
            <Button
              type="button"
              variant="primary"
              size="lg"
              disabled={!totpComplete || busy !== null}
              busy={busy === 'approve'}
              busyLabel={t('approve')}
              onClick={approve}
            >
              {t('approve')}
            </Button>
            <p className="text-2xs text-[var(--text-muted)]">{t('approveConfirm')}</p>
          </form>

          {/* Reject. Same column width, same button size, one click to open. */}
          <div className="flex flex-col gap-3">
            <DialogRoot>
              <DialogTrigger asChild>
                <Button variant="secondary" size="lg" disabled={busy !== null}>
                  {t('reject')}
                </Button>
              </DialogTrigger>
              <DialogContent title={t('reject')} description={t('rejectReason')}>
                <div className="flex flex-col gap-4">
                  <RadioGroup
                    legend={t('rejectReason')}
                    value={reason}
                    onValueChange={(value) => setReason(value as RejectionReason)}
                    options={REJECTION_REASONS.map((value) => ({
                      value,
                      label: reasons(value),
                    }))}
                  />
                  <Textarea
                    label={t('rejectNote')}
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    maxLength={1000}
                  />
                  <Button
                    variant="primary"
                    size="lg"
                    busy={busy === 'reject'}
                    busyLabel={t('rejectSubmit')}
                    onClick={reject}
                  >
                    {t('rejectSubmit')}
                  </Button>
                </div>
              </DialogContent>
            </DialogRoot>
            <p className="text-2xs text-[var(--text-muted)]">
              {/* The reason taxonomy is fixed because rejections are the training signal
                  the Learn loop runs on, and free text cannot be aggregated. */}
              {t('rejectReason')} — {common('review')}
            </p>
          </div>
        </section>
      )}
    </div>
  );
}

function Committing({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">{label}</span>
      <span data-sarana-datum="" className="font-mono text-lg font-semibold">
        {value}
      </span>
    </div>
  );
}

function IncidentRow({ incident }: { readonly incident: Incident }) {
  const t = useTranslations('cop');
  return (
    <li
      className={cn(
        'flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--radius-default)]',
        'border border-[var(--divider)] bg-[var(--surface-card)] px-3 py-2',
      )}
    >
      <SeverityPill level={incident.severity as 0 | 1 | 2 | 3 | 4} locale="en" />
      <ReferenceCode code={incident.public_ref} />
      <span className="text-sm">{incident.gn_division_code}</span>
      <span className="text-xs text-[var(--text-muted)]">
        {t('peopleAtRisk')}:{' '}
        <span data-sarana-datum="" className="font-mono">
          {incident.people_at_risk}
        </span>
      </span>
      <span className="ml-auto">
        <RelativeTime value={incident.first_reported_at} />
      </span>
    </li>
  );
}
