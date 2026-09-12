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
import { useEffect, useRef, useState } from 'react';

import { Link } from '../i18n/routing';
import { gatewayFetch } from '../lib/gateway-client';
import { usePlan, usePlanIncidents, useInvalidateGates, useResponders } from '../lib/queries';
import {
  REJECTION_REASONS,
  decisionResponseSchema,
  type Incident,
  type IncidentFactors,
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
  const reasoning = plan.data.reasoning;
  const factorsByIncident = new Map(
    (reasoning?.factors ?? []).map((entry) => [entry.incident_id, entry]),
  );
  // Only the responders this plan commits. The map should not draw every team in the
  // country behind a route that uses two of them.
  const planResponders = plan.data.responder_ids
    .map((id) => responderById.get(id))
    .filter((responder): responder is Responder => responder !== undefined);

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
        `unservable` sits above the decision, not below it. It is the incident nobody can
        reach, and it is often the most decision-relevant thing on the page: the dispatcher
        escalates it to a different agency rather than approving around it. A plan that
        showed only what it proposed would look complete while a household waited.
      */}
      <UnservableList unservable={reasoning?.unservable ?? []} incidents={incidents.data ?? []} />

      {reasoning === null ? (
        // Null, not empty. Nothing recorded a reason for this plan - which happens when it
        // was proposed by something other than the triage agent. An empty factor list under
        // a "why these are ranked here" heading would instead say the agent weighed
        // nothing, which is a different and much worse claim.
        <DegradedBanner kind="reasoning" />
      ) : null}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('routeMap')}</h2>
        <RouteMap
          routes={reasoning?.routes ?? []}
          incidents={incidents.data ?? []}
          responders={planResponders}
        />
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('whyRanked')}</h2>
        {/* Expanded, never behind a disclosure. If the operator has to click to see why
            incident 3 outranks incident 4, they stop looking at it by hour six and the
            gate becomes a button rather than a decision. */}
        <p className="text-2xs text-[var(--text-muted)]">{t('whyRankedHint')}</p>
        {incidents.isPending ? (
          <Skeleton className="h-32" />
        ) : incidents.isError ? (
          <ErrorPanel error={incidents.error} />
        ) : (
          <ul className="flex flex-col gap-2">
            {(incidents.data ?? []).map((incident) => (
              <IncidentRow
                key={incident.id}
                incident={incident}
                factors={factorsByIncident.get(incident.id) ?? null}
              />
            ))}
          </ul>
        )}
      </section>

      {reasoning?.rationale ? (
        <section className="flex flex-col gap-1 rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-4">
          <h2 className="text-sm font-medium">{t('rationale')}</h2>
          <p className="text-sm">{reasoning.rationale}</p>
          {/* How the prose was produced. "TEMPLATE" and a model name are weighed
              differently, and a sentence with no attribution is one a dispatcher cannot
              weigh at all. Same reason the queue shows its `ordering`. */}
          <p className="text-2xs text-[var(--text-muted)]">
            {t('rationaleMethod')}:{' '}
            <span data-sarana-datum="" className="font-mono">
              {reasoning.rationale_method ?? '—'}
            </span>
            {reasoning.method ? (
              <>
                {' · '}
                {t('routingMethod')}:{' '}
                <span data-sarana-datum="" className="font-mono">
                  {reasoning.method}
                  {reasoning.status ? ` (${reasoning.status})` : null}
                </span>
              </>
            ) : null}
          </p>
        </section>
      ) : null}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('responders')}</h2>
        <ul className="flex flex-wrap gap-2">
          {plan.data.responder_ids.map((id) => {
            const responder = responderById.get(id);
            return (
              <li key={id}>
                <Badge tone={responder?.status === 'AVAILABLE' ? 'verified' : 'neutral'}>
                  {/* The organisation, which is what the schema carries. There is no
                      per-unit callsign; the console assumed one once and the assumption
                      failed silently at the zod boundary, emptying this list. */}
                  <span className="font-mono">{responder?.org ?? id.slice(0, 8)}</span>
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

/**
 * Every incident the solver could not fit, with the reason.
 *
 * Prominent and above the decision, because it is often what the decision turns on. It
 * renders nothing when the list is empty rather than an empty panel: "no unservable
 * incidents" and "the plan did not record any" look identical on screen, and only one of
 * them is a statement about the plan.
 */
function UnservableList({
  unservable,
  incidents,
}: {
  readonly unservable: readonly Unservable[];
  readonly incidents: readonly Incident[];
}) {
  const t = useTranslations('dispatch');
  if (unservable.length === 0) return null;

  const byId = new Map(incidents.map((incident) => [incident.id, incident]));

  return (
    <section
      // The warning band, not the watch band. An incident nobody is going to is a hazard
      // condition rather than a degraded service, and this is the one place on the screen
      // where that register is the correct one.
      role="alert"
      data-unservable-count={unservable.length}
      className={cn(
        'flex flex-col gap-2 rounded-[var(--radius-default)] border-2 px-4 py-3',
        'border-[var(--sev-3-border)] bg-[var(--sev-3-bg)] text-[var(--sev-3-fg)]',
      )}
    >
      <h2 className="text-sm font-semibold">{t('unservable', { count: unservable.length })}</h2>
      <p className="text-xs opacity-90">{t('unservableHint')}</p>
      <ul className="flex flex-col gap-1.5">
        {unservable.map((item) => {
          const incident = byId.get(item.incident_id);
          return (
            <li key={item.incident_id} className="flex flex-wrap items-baseline gap-x-3 text-xs">
              <ReferenceCode code={incident?.public_ref ?? item.incident_id.slice(0, 8)} />
              {incident ? (
                <span data-sarana-datum="" className="font-mono">
                  {incident.gn_division_code}
                </span>
              ) : null}
              <Badge tone="pending">{item.reason}</Badge>
              {item.detail ? <span className="opacity-90">{item.detail}</span> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * One incident in the plan, with why it is ranked where it is.
 *
 * The breakdown is inline rather than behind a popover, unlike the queue's. The queue's
 * job is comparison across many rows at a glance; this screen's job is one decision made
 * properly, and the whole argument for it has to be readable without a further click.
 */
function IncidentRow({
  incident,
  factors,
}: {
  readonly incident: Incident;
  readonly factors: IncidentFactors | null;
}) {
  const t = useTranslations('cop');
  const dispatch = useTranslations('dispatch');

  // Sorted by contribution. The heaviest term is the answer to "why is this here", and
  // an alphabetical list makes the operator do the sorting.
  const contributions = Object.entries(
    (factors?.factors?.['contributions'] as Record<string, unknown> | undefined) ??
      factors?.factors ??
      {},
  )
    .filter((entry): entry is [string, number] => typeof entry[1] === 'number')
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));

  return (
    <li
      data-incident-ref={incident.public_ref}
      className={cn(
        'flex flex-col gap-2 rounded-[var(--radius-default)]',
        'border border-[var(--divider)] bg-[var(--surface-card)] px-3 py-2',
      )}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {factors?.rank ? (
          <span data-sarana-datum="" className="font-mono text-2xs text-[var(--text-muted)]">
            {factors.rank}
          </span>
        ) : null}
        <SeverityPill level={incident.severity as 0 | 1 | 2 | 3 | 4} locale="en" />
        <ReferenceCode code={incident.public_ref} />
        <span className="text-sm">{incident.gn_division_code}</span>
        <span className="text-xs text-[var(--text-muted)]">
          {t('peopleAtRisk')}:{' '}
          <span data-sarana-datum="" className="font-mono">
            {incident.people_at_risk}
          </span>
        </span>
        {/* Location confidence reduces dispatchability and never urgency: a report the
            platform cannot place is not less urgent, it is harder to reach. */}
        {factors?.dispatchable === false ? (
          <Badge tone="pending">{dispatch('notDispatchable')}</Badge>
        ) : null}
        <span className="ml-auto">
          <RelativeTime value={incident.first_reported_at} />
        </span>
      </div>

      {factors ? (
        <div className="flex flex-col gap-1 border-t border-[var(--divider)] pt-2">
          {factors.explanation ? <p className="text-xs">{factors.explanation}</p> : null}
          {contributions.length > 0 ? (
            <dl className="flex flex-wrap gap-x-6 gap-y-1">
              {contributions.map(([name, value]) => (
                <div key={name} className="flex items-baseline gap-2 text-2xs">
                  <dt className="text-[var(--text-muted)]">{name}</dt>
                  <dd data-sarana-datum="" className="font-mono">
                    {value.toFixed(3)}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
          <p className="text-2xs text-[var(--text-muted)]">
            {dispatch('score')}:{' '}
            <span data-sarana-datum="" className="font-mono">
              {factors.score === null ? '—' : factors.score.toFixed(3)}
            </span>
            {' · '}
            {t('orderedBy')}:{' '}
            <span data-sarana-datum="" className="font-mono">
              {factors.model_version ?? factors.method ?? '—'}
            </span>
          </p>
        </div>
      ) : (
        // This incident is in the plan and the plan's reasoning does not mention it. Said
        // plainly rather than left blank: a row with no explanation beside rows that have
        // one reads as an oversight in the screen rather than a gap in the record.
        <p className="border-t border-[var(--divider)] pt-2 text-2xs text-[var(--text-muted)]">
          {dispatch('noFactorsForIncident')}
        </p>
      )}
    </li>
  );
}
