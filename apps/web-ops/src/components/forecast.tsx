'use client';

/**
 * `/ops/forecast` — impact forecasts by division, their drivers, and the triggers.
 *
 * This is the anticipatory half of the platform, and it is the screen that answers the
 * question everything before an event turns on: which divisions, how many households, and
 * how long have we got.
 *
 * Four rules run through it.
 *
 * **A rule-derived class is never shown as a model's.** `method` is `RULE_THRESHOLD` or
 * `MODEL` and the screen says which on every row. This is the same failure the triage
 * queue's `assisted` flag exists to prevent, one loop further upstream: a threshold
 * crossing presented as a prediction invites an operator to trust it as one.
 *
 * **Impact class is a severity, so it uses the severity ramp.** Unlike delivery
 * confirmation or queue age, an impact class *is* a hazard grade - 4 is the evacuate line
 * - and it is the one derived number on the console that legitimately borrows those five
 * colours.
 *
 * **Every driver is rendered, including one this screen has never seen.** The table's
 * CHECK constraint requires `drivers` to be non-empty for exactly this reason: a forecast
 * with no account of what moved it is not reviewable. Dropping an unrecognised key would
 * silently omit the term that mattered.
 *
 * **Lead time is shown as a duration, beside the validity window.** "Class 4" with no
 * lead time is not actionable; "class 4, 26 hours out, valid until 06:00" is the
 * difference between a warning and a note.
 */

import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ConfidenceMeter,
  ReferenceCode,
  RelativeTime,
  Select,
  SeverityPill,
  Skeleton,
  StatCard,
  cn,
} from '@sarana/ui';
import type { ConfidenceBand, SeverityLevel } from '@sarana/ui';
import { localised, type Locale } from '@sarana/ts-shared/i18n';
import { formatDateTime } from '@sarana/ts-shared/format';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  useAnticipatoryTriggers,
  useForecastHistory,
  useHazardEvents,
  useImpactForecasts,
} from '../lib/queries';
import { anchorEvent, type AnticipatoryTrigger, type ImpactForecast } from '../lib/schemas';
import { DegradedBanner, ErrorPanel } from './degraded';

/**
 * The class at and above which a forecast is worth an operator's attention by default.
 *
 * 1, not 0. Class 0 is "no expected impact" and on most days it is most of the country;
 * a default that included it would open this screen on fourteen thousand rows of nothing
 * and bury the four that matter. The filter is on screen so raising or lowering it is a
 * deliberate act rather than a hidden default.
 */
const DEFAULT_MIN_CLASS = 1;

/** Only the evacuate line. The rest of the ramp is graded response, not evacuation. */
const EVACUATE_CLASS = 4;

function bandFor(confidence: number): ConfidenceBand {
  if (confidence >= 0.75) return 'high';
  if (confidence >= 0.5) return 'medium';
  return 'low';
}

/** Whether this row came from a model or from a published threshold. */
function isModelDerived(forecast: ImpactForecast): boolean {
  return forecast.method === 'MODEL';
}

export function ForecastBoard() {
  const t = useTranslations('forecast');
  const cop = useTranslations('cop');
  const locale = useLocale() as Locale;

  const events = useHazardEvents();
  const [eventId, setEventId] = useState<string>('');
  const [minClass, setMinClass] = useState<number>(DEFAULT_MIN_CLASS);
  const [selected, setSelected] = useState<ImpactForecast | null>(null);

  // Default to the event the console is already anchored to, so the forecast screen and
  // the time spine across the top of every page are talking about the same cyclone.
  const anchored = anchorEvent(events.data ?? []);
  const activeEventId = eventId || anchored?.id || '';

  const forecasts = useImpactForecasts(activeEventId || undefined, minClass);
  const triggers = useAnticipatoryTriggers(activeEventId || undefined);

  if (forecasts.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={forecasts.error} />
      </div>
    );
  }

  const rows = forecasts.data ?? [];
  const evacuate = rows.filter((row) => row.impact_class >= EVACUATE_CLASS);
  const households = rows.reduce((total, row) => total + row.expected_households_affected, 0);
  // The shortest lead time across the rows that matter. It is the clock the operator is
  // actually working against, and an average would flatter it.
  const soonest = rows.length
    ? Math.min(...rows.map((row) => row.lead_time_hours))
    : null;
  const anyModelDerived = rows.some(isModelDerived);

  /**
   * When the newest run behind these figures was generated.
   *
   * The newest, not the oldest: the tiles summarise the current picture, and the current
   * picture is only as fresh as its most recent input. Saying "no forecast yet" rather
   * than stamping the render time is the difference between an empty board and one that
   * claims to be up to date.
   */
  const newestRun = rows.reduce<string | null>(
    (latest, row) => (latest === null || row.generated_at > latest ? row.generated_at : latest),
    null,
  );
  const generatedLabel =
    newestRun === null
      ? t('noRunYet')
      : `${t('generated')} ${formatDateTime(newestRun, locale)}`;

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">{t('title')}</h1>
        <p className="text-xs text-[var(--text-muted)]">{t('subtitle')}</p>
      </header>

      {/* Every row derived from a published threshold rather than a model. Not an error -
          the rule engine is the deterministic path and it is what runs today - but a
          threshold crossing read as a prediction is read with more confidence than it
          earns, so the screen says so before the table rather than in a column footnote. */}
      {rows.length > 0 && !anyModelDerived ? <DegradedBanner kind="agent" /> : null}

      <div className="flex flex-wrap items-end gap-4">
        <Select
          label={t('hazardEvent')}
          placeholder={t('allEvents')}
          value={activeEventId}
          onValueChange={setEventId}
          options={(events.data ?? []).map((event) => ({
            value: event.id,
            label: `${localised(event.name, locale)} · ${event.status}`,
          }))}
        />
        <Select
          label={t('minClass')}
          value={String(minClass)}
          onValueChange={(value) => setMinClass(Number(value))}
          options={[0, 1, 2, 3, 4].map((level) => ({
            value: String(level),
            label: t('classAtLeast', { level }),
          }))}
        />
      </div>

      {/* `asOf` is required by `StatCard` and it is the point: a figure on an incident
          dashboard with no timestamp looks live and may be an hour old. These are derived
          from forecast runs, so the honest stamp is the newest run behind them - not the
          time the page rendered, which would be a claim about the wrong clock. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t('divisionsForecast')}
          value={rows.length.toLocaleString('en-LK')}
          asOf={generatedLabel}
        />
        <StatCard
          label={t('divisionsEvacuate')}
          value={evacuate.length.toLocaleString('en-LK')}
          context={t('divisionsEvacuateHint')}
          asOf={generatedLabel}
        />
        <StatCard
          label={t('households')}
          value={households.toLocaleString('en-LK')}
          asOf={generatedLabel}
        />
        <StatCard
          label={t('soonest')}
          value={soonest === null ? '—' : t('hours', { count: soonest })}
          context={t('soonestHint')}
          asOf={generatedLabel}
        />
      </div>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('byDivision')}</h2>
        {forecasts.isPending ? (
          <Skeleton className="h-64" />
        ) : (
          <DataTable<ImpactForecast>
            caption={t('byDivision')}
            rows={rows}
            rowKey={(row) => row.id}
            height="28rem"
            onRowActivate={setSelected}
            empty={<EmptyState title={t('empty')} description={t('emptyHint')} />}
            columns={[
              {
                key: 'class',
                header: t('impactClass'),
                width: '11rem',
                cell: (row) => (
                  <SeverityPill level={row.impact_class as SeverityLevel} locale="en" />
                ),
              },
              {
                key: 'division',
                header: cop('division'),
                width: '11rem',
                cell: (row) => (
                  <span data-sarana-datum="" className="font-mono text-xs">
                    {row.gn_division_code}
                  </span>
                ),
              },
              {
                key: 'households',
                header: t('households'),
                width: '10rem',
                numeric: true,
                cell: (row) => (
                  <span data-sarana-datum="" className="font-mono">
                    {row.expected_households_affected.toLocaleString('en-LK')}
                  </span>
                ),
              },
              {
                key: 'lead',
                header: t('leadTime'),
                width: '9rem',
                numeric: true,
                cell: (row) => (
                  <span data-sarana-datum="" className="font-mono">
                    {t('hours', { count: row.lead_time_hours })}
                  </span>
                ),
              },
              {
                key: 'road',
                header: t('roadAccess'),
                width: '11rem',
                cell: (row) =>
                  row.expected_road_access_loss ? (
                    <Badge tone="pending">{t('roadAccessLost')}</Badge>
                  ) : (
                    <span className="text-2xs text-[var(--text-muted)]">{t('roadAccessKept')}</span>
                  ),
              },
              {
                key: 'method',
                header: t('method'),
                width: '13rem',
                // On every row, not once at the top. A reader scanning the table
                // sideways must not be able to lose track of which rows a model produced.
                cell: (row) => (
                  <span className="flex flex-col">
                    <Badge tone={isModelDerived(row) ? 'verified' : 'neutral'}>
                      {isModelDerived(row) ? t('modelDerived') : t('ruleDerived')}
                    </Badge>
                    {row.model_version ? (
                      <span data-sarana-datum="" className="mt-0.5 font-mono text-2xs">
                        {row.model_version}
                      </span>
                    ) : null}
                  </span>
                ),
              },
              {
                key: 'generated',
                header: t('generated'),
                cell: (row) => <RelativeTime value={row.generated_at} />,
              },
            ]}
          />
        )}
      </section>

      {selected ? (
        <ForecastDetail forecast={selected} onClose={() => setSelected(null)} />
      ) : (
        <p className="text-2xs text-[var(--text-muted)]">{t('selectDivision')}</p>
      )}

      <TriggerList triggers={triggers.data ?? []} error={triggers.error} />
    </div>
  );
}

/**
 * One division's forecast, its drivers, and every run that preceded it.
 *
 * The history is the half that makes a forecast reviewable. "Did we see this coming" is
 * asked after every event and cannot be answered from the current row alone: what matters
 * is when the class first rose and how far ahead that was.
 */
function ForecastDetail({
  forecast,
  onClose,
}: {
  readonly forecast: ImpactForecast;
  readonly onClose: () => void;
}) {
  const t = useTranslations('forecast');
  const common = useTranslations('common');
  const cop = useTranslations('cop');
  const locale = useLocale() as Locale;
  const history = useForecastHistory(forecast.gn_division_code);

  return (
    <section
      className={cn(
        'flex flex-col gap-4 rounded-[var(--radius-default)] border p-4',
        forecast.impact_class >= EVACUATE_CLASS
          ? 'border-[var(--sev-4-border)] bg-[var(--sev-4-bg)] text-[var(--sev-4-fg)]'
          : 'border-[var(--divider)] bg-[var(--surface-card)]',
      )}
    >
      <header className="flex flex-wrap items-center gap-3">
        <SeverityPill level={forecast.impact_class as SeverityLevel} locale="en" />
        <ReferenceCode code={forecast.gn_division_code} kind={cop('division')} />
        <Badge tone={isModelDerived(forecast) ? 'verified' : 'neutral'}>
          {isModelDerived(forecast) ? t('modelDerived') : t('ruleDerived')}
        </Badge>
        <Button variant="ghost" size="sm" onClick={onClose} className="ml-auto">
          {common('close')}
        </Button>
      </header>

      <dl className="grid gap-3 sm:grid-cols-3">
        <Definition label={t('leadTime')} value={t('hours', { count: forecast.lead_time_hours })} />
        <Definition
          label={t('households')}
          value={forecast.expected_households_affected.toLocaleString('en-LK')}
        />
        <Definition
          label={t('validity')}
          value={`${formatDateTime(forecast.valid_from, locale)} – ${formatDateTime(forecast.valid_to, locale)}`}
        />
      </dl>

      <div>
        <h3 className="mb-1 text-sm font-medium">{t('confidence')}</h3>
        {/* The consequence beside the number. A confidence figure with nothing following
            from it is a figure an operator learns to scroll past. */}
        <ConfidenceMeter
          value={forecast.confidence}
          band={bandFor(forecast.confidence)}
          bandLabel={t('confidence')}
          consequence={t('confidenceHint')}
        />
      </div>

      <div>
        <h3 className="mb-1 text-sm font-medium">{t('drivers')}</h3>
        <p className="mb-2 text-2xs text-[var(--text-muted)]">{t('driversHint')}</p>
        {/* Walked structurally and rendered key by key. A driver name this screen has
            never seen is rendered rather than dropped: the one it does not recognise is
            the term the model just started using, and omitting it silently would remove
            the reason from a record whose whole purpose is carrying one. */}
        <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
          {Object.entries(forecast.drivers).map(([name, value]) => (
            <div key={name} className="flex items-baseline justify-between gap-4 text-xs">
              <dt className="text-[var(--text-muted)]">{name}</dt>
              <dd data-sarana-datum="" className="font-mono">
                {typeof value === 'number'
                  ? value.toLocaleString('en-LK', { maximumFractionDigits: 3 })
                  : typeof value === 'boolean' || value === null
                    ? String(value)
                    : typeof value === 'string'
                      ? value
                      : JSON.stringify(value)}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <div>
        <h3 className="mb-1 text-sm font-medium">{t('historyTitle')}</h3>
        <p className="mb-2 text-2xs text-[var(--text-muted)]">{t('historyHint')}</p>
        {history.isPending ? (
          <Skeleton line />
        ) : history.isError ? (
          <p className="text-xs text-[var(--sev-2-fg)]">{t('historyUnavailable')}</p>
        ) : (
          <ol className="flex flex-col gap-1">
            {(history.data ?? []).map((run) => (
              <li key={run.id} className="flex flex-wrap items-center gap-3 text-2xs">
                <SeverityPill level={run.impact_class as SeverityLevel} locale="en" />
                <span data-sarana-datum="" className="font-mono">
                  {t('hours', { count: run.lead_time_hours })}
                </span>
                <span className="text-[var(--text-muted)]">
                  {formatDateTime(run.generated_at, locale)}
                </span>
                <span className="text-[var(--text-muted)]">
                  {isModelDerived(run) ? t('modelDerived') : t('ruleDerived')}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

/**
 * The anticipatory triggers, fired ones first.
 *
 * A trigger is a condition agreed *before* the disaster, which is the only time that
 * argument is worth having. Rendering the condition verbatim is the point: a trigger
 * nobody can read is a trigger nobody agreed to.
 */
function TriggerList({
  triggers,
  error,
}: {
  readonly triggers: readonly AnticipatoryTrigger[];
  readonly error: unknown;
}) {
  const t = useTranslations('forecast');
  const cop = useTranslations('cop');

  if (error) return <ErrorPanel error={error} />;

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium">{t('triggersTitle')}</h2>
      <p className="text-xs text-[var(--text-muted)]">{t('triggersHint')}</p>
      {triggers.length === 0 ? (
        <EmptyState title={t('triggersEmpty')} description={t('triggersEmptyHint')} />
      ) : (
        <ul className="flex flex-col gap-2">
          {triggers.map((trigger) => (
            <li
              key={trigger.id}
              data-trigger-fired={trigger.fired_at !== null}
              className={cn(
                'flex flex-col gap-1 rounded-[var(--radius-default)] border px-3 py-2',
                trigger.fired_at
                  ? 'border-[var(--pending)] bg-[var(--surface-raised)]'
                  : 'border-[var(--divider)] bg-[var(--surface-card)]',
              )}
            >
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <Badge tone={trigger.fired_at ? 'pending' : 'neutral'}>
                  {trigger.fired_at ? t('fired') : t('armed')}
                </Badge>
                {trigger.gn_division_code ? (
                  <span data-sarana-datum="" className="font-mono">
                    {trigger.gn_division_code}
                  </span>
                ) : (
                  <span className="text-[var(--text-muted)]">{cop('division')}: —</span>
                )}
                {trigger.fired_at ? (
                  <>
                    <RelativeTime value={trigger.fired_at} />
                    {/* A fired trigger always names an action, even when the action was
                        to do nothing. A CHECK on the table enforces it, so an empty cell
                        here would be a bug rather than a blank. */}
                    <Badge tone="neutral">{trigger.action_taken ?? '—'}</Badge>
                  </>
                ) : null}
              </div>
              <p data-sarana-datum="" className="font-mono text-2xs text-[var(--text-muted)]">
                {JSON.stringify(trigger.condition)}
              </p>
              {trigger.notes ? <p className="text-xs">{trigger.notes}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Definition({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">{label}</dt>
      <dd data-sarana-datum="" className="font-mono text-sm">
        {value}
      </dd>
    </div>
  );
}
