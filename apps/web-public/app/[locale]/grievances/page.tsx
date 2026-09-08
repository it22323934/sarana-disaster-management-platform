/**
 * `/grievances` — the complaint rate, published by the institution being complained about.
 *
 * The brief calls this page "a commitment", and the commitment is the one thing the layout
 * has to protect: the numbers go at the top, not below an explanation of why they are
 * high. The reasoning about what a low complaint count does and does not mean goes
 * underneath, where it reads as context rather than as a preface managing expectations.
 *
 * The confirmation rate is shown beside the complaint counts because on their own they
 * invite the wrong reading. A district with no complaints and a 40% confirmation rate is
 * not doing well; it is a district where the mechanism has not reached anybody.
 */

import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import type { Locale } from '@sarana/ts-shared/i18n';

import { PageShell, SiteFooter, SiteHeader } from '../../../src/components/chrome';
import { Figure, ReadFailure, ScrollableTable } from '../../../src/components/provenance';
import { formatCount, formatDays, formatPercent, localisedName, secondsToDays } from '../../../src/lib/format';
import { getAreaDistricts, getConfirmationRate, getGrievanceStats, nameIndex } from '../../../src/lib/public-api';

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

/** What the ledger service returns when a grievance has no DS division assigned yet. */
const UNASSIGNED = 'UNASSIGNED';

export async function generateMetadata({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'grievances' });
  return { title: t('title'), description: t('lead') };
}

export default async function GrievancesPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: 'grievances' });
  const common = await getTranslations({ locale, namespace: 'common' });
  const errors = await getTranslations({ locale, namespace: 'errors' });
  const home = await getTranslations({ locale, namespace: 'home' });

  const [stats, areas, confirmation] = await Promise.all([
    getGrievanceStats(),
    getAreaDistricts(),
    getConfirmationRate(),
  ]);
  const names = areas.ok ? nameIndex(areas.data.districts) : new Map();

  const totals = stats.ok
    ? stats.data.districts.reduce(
        (sum, row) => ({
          total: sum.total + row.total,
          open: sum.open + row.open_count,
          breached: sum.breached + row.breached_count,
        }),
        { total: 0, open: 0, breached: 0 },
      )
    : null;

  return (
    <>
      <SiteHeader locale={locale} pathname="/grievances" />
      <PageShell title={t('title')} lead={t('lead')}>
        {!stats.ok ? (
          <ReadFailure
            reason={stats.reason}
            title={errors('title')}
            explanation={errors(stats.reason)}
            whatToDo={errors('whatToDo')}
            neverZero={errors('neverZero')}
          />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Figure label={t('raised')} value={formatCount(totals?.total ?? 0)} />
              <Figure label={t('open')} value={formatCount(totals?.open ?? 0)} />
              <Figure label={t('breached')} value={formatCount(totals?.breached ?? 0)} />
              <Figure
                label={home('confirmed')}
                value={
                  confirmation.ok ? formatPercent(confirmation.data.confirmation_rate) : '—'
                }
                context={t('readAlongside')}
              />
            </div>

            {stats.data.districts.length === 0 ? (
              <p className="mt-6 text-sm text-[var(--text-muted)]">{t('noGrievances')}</p>
            ) : (
              <div className="mt-6">
                <ScrollableTable label={t('title')}>
                  <table className="w-full border-collapse text-sm">
                    <caption className="sr-only">{t('lead')}</caption>
                    <thead>
                      <tr className="bg-[var(--surface-raised)] text-left">
                        <th scope="col" className="px-3 py-2 font-medium">
                          {common('district')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-medium">
                          {t('raised')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-medium">
                          {t('open')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-medium">
                          {t('closed')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-medium">
                          {t('breached')}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-medium">
                          {t('medianDays')}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.data.districts.map((row) => (
                        <tr key={row.district_code} className="border-t border-[var(--divider)]">
                          <th scope="row" className="px-3 py-2 text-left font-normal">
                            {row.district_code === UNASSIGNED ? (
                              // Not a district. Named as what it is rather than shown as a
                              // code nobody can look up.
                              <span className="text-[var(--text-muted)]">{t('unassigned')}</span>
                            ) : (
                              <>
                                {localisedName(
                                  names.get(row.district_code),
                                  locale,
                                  row.district_code,
                                )}
                                <span className="block text-2xs text-[var(--text-muted)]">
                                  {row.district_code}
                                </span>
                              </>
                            )}
                          </th>
                          <td data-sarana-datum="" className="px-3 py-2 text-right">
                            {formatCount(row.total)}
                          </td>
                          <td data-sarana-datum="" className="px-3 py-2 text-right">
                            {formatCount(row.open_count)}
                          </td>
                          <td data-sarana-datum="" className="px-3 py-2 text-right">
                            {formatCount(row.closed_count)}
                          </td>
                          <td data-sarana-datum="" className="px-3 py-2 text-right">
                            {formatCount(row.breached_count)}
                          </td>
                          <td data-sarana-datum="" className="px-3 py-2 text-right">
                            {formatDays(secondsToDays(row.median_resolution_seconds))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollableTable>
              </div>
            )}

            <section aria-labelledby="commitment" className="mt-8 max-w-prose">
              <h2
                id="commitment"
                className="m-0 text-lg font-semibold text-[var(--text-primary)]"
              >
                {t('commitmentTitle')}
              </h2>
              <p className="mt-2 text-sm text-[var(--text-muted)]">{t('commitmentBody')}</p>
              <p className="mt-3 text-sm text-[var(--text-muted)]">{t('readAlongside')}</p>
              {confirmation.ok ? (
                <p className="mt-2 text-sm text-[var(--text-muted)]">{confirmation.data.note}</p>
              ) : null}
              <p className="mt-2 text-sm text-[var(--text-muted)]">{stats.data.note}</p>
            </section>
          </>
        )}
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
