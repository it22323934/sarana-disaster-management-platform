/**
 * `/alerts` — public alert history, active alerts first.
 *
 * **Every alert shows what it was sent to and what it actually reached, side by side.** A
 * warning dispatched to 12,000 contacts and confirmed to 4,000 is the most important fact
 * about that warning, and `reached` on its own reads as a success. The gap is rendered as
 * its own figure rather than left for a reader to subtract.
 *
 * The severity band is rendered with `SeverityPill`, which is one of the few design-system
 * components that is not a client component — it is a pure renderer, so it costs this route
 * no JavaScript. The band is also written as a word, because the reserved severity ramp is
 * deliberately not discriminable in greyscale (file 19 has a test asserting that) and this
 * page prints.
 */

import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import { formatDateTime } from '@sarana/ts-shared/format';
import type { Locale } from '@sarana/ts-shared/i18n';

import { PageShell, SiteFooter, SiteHeader } from '../../../src/components/chrome';
import { Figure, ReadFailure } from '../../../src/components/provenance';
import { formatCount, formatPercent, localisedName } from '../../../src/lib/format';
import { getAlerts, type PublicAlert } from '../../../src/lib/public-api';

/**
 * Five minutes, from the brief.
 *
 * Written as a literal because Next statically analyses this export and rejects an
 * imported identifier ("Unknown identifier ... at revalidate"). `REVALIDATE_SECONDS` in
 * `src/lib/services.ts` stays the documented source of truth and
 * `src/lib/revalidate.test.ts` asserts every page's literal still matches it, so the two
 * cannot drift without a test failing.
 */
export const revalidate = 300;

export async function generateMetadata({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'alerts' });
  return { title: t('title'), description: t('lead') };
}

function AlertCard({
  alert,
  locale,
  labels,
}: {
  readonly alert: PublicAlert;
  readonly locale: Locale;
  readonly labels: Readonly<Record<string, string>>;
}) {
  const notReached = Math.max(0, alert.targeted - alert.reached);

  return (
    <article
      className="rounded-[var(--radius-surface)] border border-[var(--divider)] bg-[var(--surface-card)] p-4"
      // Cancelled alerts stay in the history, and the marker is an attribute rather than
      // only a visual treatment so the e2e suite can assert they are present.
      data-alert-status={alert.status}
    >
      <div className="flex flex-wrap items-baseline gap-3">
        <h3 className="m-0 text-base font-semibold text-[var(--text-primary)]">
          {localisedName(alert.headline, locale, alert.cap_identifier)}
        </h3>
        {alert.status === 'CANCELLED' ? (
          <span className="rounded-[var(--radius-cell)] border border-[var(--pending)] px-2 py-0.5 text-2xs font-medium text-[var(--pending)]">
            {labels['cancelled']}
          </span>
        ) : null}
      </div>

      <p className="mt-2 max-w-prose text-sm text-[var(--text-muted)]">
        {localisedName(alert.description, locale, '')}
      </p>

      <div className="mt-3">
        <p className="m-0 text-xs font-medium text-[var(--text-primary)]">
          {labels['instruction']}
        </p>
        <p className="mt-1 max-w-prose text-sm text-[var(--text-muted)]">
          {localisedName(alert.instruction, locale, '')}
        </p>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {labels['severity']}
          </dt>
          <dd className="m-0 font-medium">{alert.severity}</dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {labels['urgency']}
          </dt>
          <dd className="m-0 font-medium">{alert.urgency}</dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {labels['certainty']}
          </dt>
          <dd className="m-0 font-medium">{alert.certainty}</dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {labels['areas']}
          </dt>
          <dd data-sarana-datum="" className="m-0 font-medium">
            {formatCount(alert.gn_division_count)}
          </dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {labels['targeted']}
          </dt>
          <dd data-sarana-datum="" className="m-0 font-medium">
            {formatCount(alert.targeted)}
          </dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {labels['reached']}
          </dt>
          <dd data-sarana-datum="" className="m-0 font-medium">
            {formatCount(alert.reached)}
            {alert.targeted > 0 ? (
              <span className="ml-1 font-normal text-[var(--text-muted)]">
                ({formatPercent(alert.reached / alert.targeted)})
              </span>
            ) : null}
          </dd>
        </div>
        {/* Its own figure, not a subtraction the reader has to do. */}
        <div>
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {labels['gap']}
          </dt>
          <dd data-sarana-datum="" className="m-0 font-medium text-[var(--text-primary)]">
            {formatCount(notReached)}
          </dd>
        </div>
        <div>
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {labels['effective']}
          </dt>
          <dd className="m-0">
            <time dateTime={alert.effective_at}>
              {formatDateTime(alert.effective_at, locale)}
            </time>
          </dd>
        </div>
      </dl>

      <p className="mt-3 text-xs">
        <a
          href={alert.cap_xml_url}
          className="text-[var(--text-accent)] underline"
          data-print-url
        >
          {labels['capLink']}
        </a>
      </p>
    </article>
  );
}

export default async function AlertsPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: 'alerts' });
  const errors = await getTranslations({ locale, namespace: 'errors' });

  const alerts = await getAlerts();

  const labels = {
    severity: t('severity'),
    urgency: t('urgency'),
    certainty: t('certainty'),
    areas: t('areas'),
    targeted: t('targeted'),
    reached: t('reached'),
    gap: t('gap'),
    effective: t('effective'),
    capLink: t('capLink'),
    cancelled: t('cancelled'),
    instruction: t('instruction'),
  };

  const active = alerts.ok ? alerts.data.alerts.filter((alert) => alert.active) : [];
  const past = alerts.ok ? alerts.data.alerts.filter((alert) => !alert.active) : [];

  return (
    <>
      <SiteHeader locale={locale} pathname="/alerts" />
      <PageShell title={t('title')} lead={t('lead')}>
        {!alerts.ok ? (
          <ReadFailure
            reason={alerts.reason}
            title={errors('title')}
            explanation={errors(alerts.reason)}
            whatToDo={errors('whatToDo')}
            neverZero={errors('neverZero')}
          />
        ) : alerts.data.alerts.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">{t('noAlerts')}</p>
        ) : (
          <>
            <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Figure
                label={t('activeTitle')}
                value={formatCount(alerts.data.active_count)}
                emphasis="quiet"
              />
              <Figure
                label={t('pastTitle')}
                value={formatCount(alerts.data.alerts.length)}
                emphasis="quiet"
              />
              <Figure
                label={t('cancelled')}
                value={formatCount(
                  alerts.data.alerts.filter((alert) => alert.status === 'CANCELLED').length,
                )}
                emphasis="quiet"
              />
            </div>

            {active.length > 0 ? (
              <section aria-labelledby="active" className="mb-8">
                <h2
                  id="active"
                  className="m-0 text-lg font-semibold text-[var(--text-primary)]"
                >
                  {t('activeTitle')}
                </h2>
                <div className="mt-3 flex flex-col gap-4">
                  {active.map((alert) => (
                    <AlertCard key={alert.id} alert={alert} locale={locale} labels={labels} />
                  ))}
                </div>
              </section>
            ) : null}

            <section aria-labelledby="past">
              <h2 id="past" className="m-0 text-lg font-semibold text-[var(--text-primary)]">
                {t('pastTitle')}
              </h2>
              <div className="mt-3 flex flex-col gap-4">
                {past.map((alert) => (
                  <AlertCard key={alert.id} alert={alert} locale={locale} labels={labels} />
                ))}
              </div>
            </section>
          </>
        )}

        <section aria-labelledby="notes" className="mt-8 max-w-prose">
          <h2 id="notes" className="sr-only">
            {t('title')}
          </h2>
          <p className="text-sm text-[var(--text-muted)]">{t('deliveryNote')}</p>
          <p className="mt-2 text-sm text-[var(--text-muted)]">{t('draftsNote')}</p>
        </section>
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
