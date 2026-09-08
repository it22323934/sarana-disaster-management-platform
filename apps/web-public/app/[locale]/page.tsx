/**
 * `/` — the overview.
 *
 * Four numbers above the fold, each with its denominator, its as-of timestamp and a link
 * to the breakdown behind it. Then, at the same size and immediately below rather than
 * folded away, the four figures that say what has not gone right.
 *
 * **The layout is the argument.** The brief is explicit that unconfirmed and disputed sit
 * next to disbursed "in the same type size", because a transparency dashboard that buries
 * its own failure rate manufactures a confidence it has not earned. So the failure grid
 * uses the same `Figure` component at the same emphasis, and there is deliberately no
 * variant that would let a later change shrink it.
 *
 * Statically generated with ISR. The five-minute revalidation is the brief's, and it is
 * the number that decides both how fresh this page is and how much load reaches five
 * Python services from a URL that may end up on a news front page.
 */

import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import type { Locale } from '@sarana/ts-shared/i18n';

import { FunnelBars } from '../../src/components/funnel';
import { PageShell, SiteFooter, SiteHeader } from '../../src/components/chrome';
import { AsOf, Figure, ReadFailure } from '../../src/components/provenance';
import { formatCount, formatLKR, formatPercent } from '../../src/lib/format';
import { getFunnel } from '../../src/lib/public-api';

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
  const t = await getTranslations({ locale, namespace: 'home' });
  return { title: t('title'), description: t('lead') };
}

export default async function OverviewPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: 'home' });
  const common = await getTranslations({ locale, namespace: 'common' });
  const errors = await getTranslations({ locale, namespace: 'errors' });
  const nav = await getTranslations({ locale, namespace: 'nav' });

  const funnel = await getFunnel();
  const at = (path: string) => `/${locale}${path}`;

  return (
    <>
      <SiteHeader locale={locale} pathname="/" />
      <PageShell title={t('title')} lead={t('lead')}>
        {!funnel.ok ? (
          <ReadFailure
            reason={funnel.reason}
            title={errors('title')}
            explanation={errors(funnel.reason)}
            whatToDo={errors('whatToDo')}
            neverZero={errors('neverZero')}
          />
        ) : (
          <>
            <section aria-labelledby="headline">
              <h2 id="headline" className="sr-only">
                {t('title')}
              </h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Figure
                  label={t('assessed')}
                  value={formatLKR(funnel.data.assessed.lkr_cents, { whole: true })}
                  context={t('assessedContext', {
                    households: formatCount(funnel.data.households),
                    divisions: formatCount(funnel.data.gn_divisions),
                  })}
                  href={at('/allocations')}
                />
                <Figure
                  label={t('approved')}
                  value={formatLKR(funnel.data.approved.lkr_cents, { whole: true })}
                  context={t('ofAssessed', {
                    percent: formatPercent(funnel.data.approved.of_previous),
                  })}
                  href={at('/allocations')}
                />
                <Figure
                  label={t('disbursed')}
                  value={formatLKR(funnel.data.disbursed.lkr_cents, { whole: true })}
                  context={t('ofApproved', {
                    percent: formatPercent(funnel.data.disbursed.of_previous),
                  })}
                  href={at('/ledger')}
                />
                <Figure
                  label={t('confirmed')}
                  value={formatLKR(funnel.data.confirmed.lkr_cents, { whole: true })}
                  context={t('ofDisbursed', {
                    percent: formatPercent(funnel.data.confirmed.of_previous),
                  })}
                  href={at('/districts')}
                />
              </div>
              <AsOf
                when={funnel.data.as_of}
                locale={locale}
                label={(when) => common('asOf', { when })}
              />
            </section>

            {/* Same component, same emphasis, one screen-height below the good news and
                not behind a disclosure. See this file's docstring. */}
            <section aria-labelledby="problems" className="mt-10">
              <h2
                id="problems"
                className="m-0 text-lg font-semibold text-[var(--text-primary)]"
              >
                {t('problemsTitle')}
              </h2>
              <p className="mt-1 max-w-prose text-sm text-[var(--text-muted)]">
                {t('problemsLead')}
              </p>

              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Figure
                  label={t('unconfirmed')}
                  value={formatCount(funnel.data.unconfirmed_count)}
                  context={t('unconfirmedContext', {
                    days: funnel.data.confirmation_window_days,
                  })}
                  footer={t('unconfirmedNote')}
                />
                <Figure
                  label={t('awaitingReply')}
                  value={formatCount(funnel.data.awaiting_reply_count)}
                  context={t('awaitingReplyContext', {
                    days: funnel.data.confirmation_window_days,
                  })}
                />
                <Figure
                  label={t('reversed')}
                  value={formatLKR(funnel.data.reversed_lkr_cents, { whole: true })}
                  context={t('reversedContext')}
                  footer={t('reversedNote')}
                />
                <Figure
                  label={t('grievancesOpen')}
                  value={formatCount(funnel.data.grievance_open_count)}
                  context={t('grievancesContext', {
                    total: formatCount(funnel.data.grievance_count),
                  })}
                  href={at('/grievances')}
                />
              </div>
            </section>

            <section aria-labelledby="spine" className="mt-10">
              <h2 id="spine" className="m-0 text-lg font-semibold text-[var(--text-primary)]">
                {t('spineTitle')}
              </h2>
              <p className="mt-1 max-w-prose text-sm text-[var(--text-muted)]">
                {t('spineLead')}
              </p>
              <div className="mt-4">
                <FunnelBars
                  caption={t('spineTitle')}
                  rows={[
                    {
                      key: 'assessed',
                      label: t('assessed'),
                      amount: funnel.data.assessed.lkr_cents,
                      formattedAmount: formatLKR(funnel.data.assessed.lkr_cents, {
                        whole: true,
                      }),
                      formattedCount: formatCount(funnel.data.assessed.count),
                      ofPrevious: null,
                      ofPreviousLabel: null,
                      href: at('/allocations'),
                      description: t('assessedContext', {
                        households: formatCount(funnel.data.households),
                        divisions: formatCount(funnel.data.gn_divisions),
                      }),
                    },
                    {
                      key: 'approved',
                      label: t('approved'),
                      amount: funnel.data.approved.lkr_cents,
                      formattedAmount: formatLKR(funnel.data.approved.lkr_cents, {
                        whole: true,
                      }),
                      formattedCount: formatCount(funnel.data.approved.count),
                      ofPrevious: formatPercent(funnel.data.approved.of_previous),
                      ofPreviousLabel: t('ofAssessed', {
                        percent: formatPercent(funnel.data.approved.of_previous),
                      }),
                      href: at('/allocations'),
                      description: t('approved'),
                    },
                    {
                      key: 'disbursed',
                      label: t('disbursed'),
                      amount: funnel.data.disbursed.lkr_cents,
                      formattedAmount: formatLKR(funnel.data.disbursed.lkr_cents, {
                        whole: true,
                      }),
                      formattedCount: formatCount(funnel.data.disbursed.count),
                      ofPrevious: formatPercent(funnel.data.disbursed.of_previous),
                      ofPreviousLabel: t('ofApproved', {
                        percent: formatPercent(funnel.data.disbursed.of_previous),
                      }),
                      href: at('/ledger'),
                      description: t('disbursed'),
                    },
                    {
                      key: 'confirmed',
                      label: t('confirmed'),
                      amount: funnel.data.confirmed.lkr_cents,
                      formattedAmount: formatLKR(funnel.data.confirmed.lkr_cents, {
                        whole: true,
                      }),
                      formattedCount: formatCount(funnel.data.confirmed.count),
                      ofPrevious: formatPercent(funnel.data.confirmed.of_previous),
                      ofPreviousLabel: t('ofDisbursed', {
                        percent: formatPercent(funnel.data.confirmed.of_previous),
                      }),
                      href: at('/districts'),
                      description: t('confirmed'),
                    },
                  ]}
                />
              </div>
            </section>

            <section aria-labelledby="verify-cta" className="mt-10">
              <div className="rounded-[var(--radius-surface)] border border-[var(--divider)] bg-[var(--surface-card)] p-5">
                <h2
                  id="verify-cta"
                  className="m-0 text-lg font-semibold text-[var(--text-primary)]"
                >
                  {t('verifyCta')}
                </h2>
                <p className="mt-2 max-w-prose text-sm text-[var(--text-muted)]">
                  {t('verifyCtaBody')}
                </p>
                <p className="mt-3">
                  <a href={at('/verify')} className="text-[var(--text-accent)] underline">
                    {nav('verify')}
                  </a>
                </p>
              </div>
            </section>
          </>
        )}

        <section aria-labelledby="not-shown" className="mt-10 max-w-prose">
          <h2 id="not-shown" className="m-0 text-base font-semibold text-[var(--text-primary)]">
            {t('notShownTitle')}
          </h2>
          <p className="mt-2 text-sm text-[var(--text-muted)]">{t('notShownBody')}</p>
          <p className="mt-2 text-sm">
            <a href={at('/methodology')} className="text-[var(--text-accent)] underline">
              {nav('methodology')}
            </a>
          </p>
        </section>
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
