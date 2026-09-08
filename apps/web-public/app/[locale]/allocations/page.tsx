/**
 * `/allocations` — the funnel as a table.
 *
 * The overview shows the four figures; this shows the arithmetic between them. One row per
 * stage, with the count, the amount and the fraction that survived from the stage above,
 * so a reader can see which step lost the money rather than only that it was lost.
 *
 * A table rather than a chart, because this is the page a journalist copies into a story.
 */

import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import type { Locale } from '@sarana/ts-shared/i18n';

import { PageShell, SiteFooter, SiteHeader } from '../../../src/components/chrome';
import { AsOf, ReadFailure, ScrollableTable } from '../../../src/components/provenance';
import { formatCount, formatLKR, formatPercent } from '../../../src/lib/format';
import { getFunnel } from '../../../src/lib/public-api';

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
  const t = await getTranslations({ locale, namespace: 'allocations' });
  return { title: t('title'), description: t('lead') };
}

export default async function AllocationsPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: 'allocations' });
  const common = await getTranslations({ locale, namespace: 'common' });
  const errors = await getTranslations({ locale, namespace: 'errors' });
  const home = await getTranslations({ locale, namespace: 'home' });

  const funnel = await getFunnel();

  return (
    <>
      <SiteHeader locale={locale} pathname="/allocations" />
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
            <ScrollableTable label={t('title')}>
              <table className="w-full border-collapse text-sm">
                <caption className="sr-only">{t('lead')}</caption>
                <thead>
                  <tr className="bg-[var(--surface-raised)] text-left">
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t('stage')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      {common('amount')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      {t('records')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      {t('ofPrevious')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ['assessed', t('assessed'), t('assessedWhat'), funnel.data.assessed],
                      ['approved', t('approved'), t('approvedWhat'), funnel.data.approved],
                      ['disbursed', t('disbursed'), t('disbursedWhat'), funnel.data.disbursed],
                      ['confirmed', t('confirmed'), t('confirmedWhat'), funnel.data.confirmed],
                    ] as const
                  ).map(([key, label, what, stage]) => (
                    <tr key={key} className="border-t border-[var(--divider)] align-top">
                      <th scope="row" className="px-3 py-2 text-left font-medium">
                        {label}
                        <span className="block max-w-prose text-xs font-normal text-[var(--text-muted)]">
                          {what}
                        </span>
                      </th>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatLKR(stage.lkr_cents, { whole: true })}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatCount(stage.count)}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {/* The first stage has nothing above it. An em dash, never 100%:
                            claiming a stage is 100% of itself is a true statement that
                            reads as a performance figure. */}
                        {stage.of_previous === null ? '—' : formatPercent(stage.of_previous)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollableTable>

            <AsOf
              when={funnel.data.as_of}
              locale={locale}
              label={(when) => common('asOf', { when })}
            />

            <section aria-labelledby="gap" className="mt-8 max-w-prose">
              <h2 id="gap" className="m-0 text-lg font-semibold text-[var(--text-primary)]">
                {t('gapTitle')}
              </h2>
              <p className="mt-2 text-sm text-[var(--text-muted)]">{t('gapBody')}</p>
              <p className="mt-3 text-sm text-[var(--text-muted)]">{t('draftsExcluded')}</p>
            </section>

            <section aria-labelledby="problems" className="mt-8">
              <h2
                id="problems"
                className="m-0 text-lg font-semibold text-[var(--text-primary)]"
              >
                {home('problemsTitle')}
              </h2>
              <ScrollableTable label={home('problemsTitle')}>
                <table className="mt-3 w-full border-collapse text-sm">
                  <tbody>
                    <tr className="border-b border-[var(--divider)] align-top">
                      <th scope="row" className="px-3 py-2 text-left font-medium">
                        {home('unconfirmed')}
                      </th>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatCount(funnel.data.unconfirmed_count)}
                      </td>
                      <td className="max-w-prose px-3 py-2 text-xs text-[var(--text-muted)]">
                        {home('unconfirmedNote')}
                      </td>
                    </tr>
                    <tr className="border-b border-[var(--divider)] align-top">
                      <th scope="row" className="px-3 py-2 text-left font-medium">
                        {home('awaitingReply')}
                      </th>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatCount(funnel.data.awaiting_reply_count)}
                      </td>
                      <td className="max-w-prose px-3 py-2 text-xs text-[var(--text-muted)]">
                        {home('awaitingReplyContext', {
                          days: funnel.data.confirmation_window_days,
                        })}
                      </td>
                    </tr>
                    <tr className="align-top">
                      <th scope="row" className="px-3 py-2 text-left font-medium">
                        {home('reversed')}
                      </th>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatLKR(funnel.data.reversed_lkr_cents, { whole: true })}
                        <span className="block text-xs font-normal text-[var(--text-muted)]">
                          {formatCount(funnel.data.reversed_count)}
                        </span>
                      </td>
                      <td className="max-w-prose px-3 py-2 text-xs text-[var(--text-muted)]">
                        {home('reversedNote')}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </ScrollableTable>
            </section>
          </>
        )}
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
