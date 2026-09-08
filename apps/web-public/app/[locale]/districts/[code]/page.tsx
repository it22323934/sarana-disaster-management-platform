/**
 * `/districts/[code]` — one district, broken down to DS division.
 *
 * The page where the privacy floor becomes visible. A DS division with between one and
 * four disbursements is withheld, and the withholding is stated as a count and an amount
 * rather than left as a gap: silent suppression looks like missing data and invites the
 * reader to conclude that nothing happened there, which is the opposite of what the
 * suppression is protecting.
 *
 * The district total row includes the withheld divisions, so the columns add up to the
 * figure on `/districts`. A page whose subtotals did not sum to the number on the previous
 * screen would cost more credibility than the suppression saves.
 */

import { notFound } from 'next/navigation';
import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import type { Locale } from '@sarana/ts-shared/i18n';

import { PageShell, SiteFooter, SiteHeader } from '../../../../src/components/chrome';
import { AsOf, Figure, ReadFailure, ScrollableTable } from '../../../../src/components/provenance';
import {
  formatCount,
  formatDays,
  formatLKR,
  formatPercent,
  localisedName,
  shortDsCode,
} from '../../../../src/lib/format';
import {
  getAreaDSDivisions,
  getAreaDistricts,
  getDistrictDetail,
  getDistrictMetrics,
  nameIndex,
} from '../../../../src/lib/public-api';

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

/** `LK-21`. Checked before the code reaches a URL, so a junk path 404s rather than 500s. */
const DISTRICT_CODE = /^LK-\d{2}$/;

export async function generateMetadata({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale; readonly code: string }>;
}): Promise<Metadata> {
  const { locale, code } = await params;
  const t = await getTranslations({ locale, namespace: 'districts' });

  if (!DISTRICT_CODE.test(code)) return { title: t('notFound') };

  const areas = await getAreaDistricts();
  const name = areas.ok
    ? localisedName(nameIndex(areas.data.districts).get(code), locale, code)
    : code;

  return { title: name, description: t('detailLead') };
}

export default async function DistrictDetailPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale; readonly code: string }>;
}) {
  const { locale, code } = await params;
  setRequestLocale(locale);

  // A malformed code is a wrong URL, not an outage, so it is the one case on this site
  // that 404s rather than rendering a stated failure.
  if (!DISTRICT_CODE.test(code)) notFound();

  const t = await getTranslations({ locale, namespace: 'districts' });
  const common = await getTranslations({ locale, namespace: 'common' });
  const errors = await getTranslations({ locale, namespace: 'errors' });
  const methodology = await getTranslations({ locale, namespace: 'methodology' });

  const [detail, areas, dsAreas, metrics] = await Promise.all([
    getDistrictDetail(code),
    getAreaDistricts(),
    getAreaDSDivisions(code),
    getDistrictMetrics(),
  ]);

  const districtName = areas.ok
    ? localisedName(nameIndex(areas.data.districts).get(code), locale, code)
    : code;
  const dsNames = dsAreas.ok ? nameIndex(dsAreas.data.ds_divisions) : new Map();
  const summary = metrics.ok
    ? metrics.data.districts.find((row) => row.district_code === code)
    : undefined;

  return (
    <>
      <SiteHeader locale={locale} pathname="/districts" />
      <PageShell
        title={districtName}
        lead={t('detailLead')}
        actions={
          <a
            href={`/${locale}/districts`}
            className="text-sm text-[var(--text-accent)] underline"
          >
            {t('backToDistricts')}
          </a>
        }
      >
        {!detail.ok ? (
          <ReadFailure
            reason={detail.reason}
            title={errors('title')}
            explanation={errors(detail.reason)}
            whatToDo={errors('whatToDo')}
            neverZero={errors('neverZero')}
          />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Figure
                label={t('metricAssessed')}
                value={formatLKR(detail.data.totals.assessed_lkr_cents, { whole: true })}
                context={t('assessedHouseholds')}
                emphasis="quiet"
                footer={formatCount(detail.data.totals.assessed_households)}
              />
              <Figure
                label={t('metricApproved')}
                value={formatLKR(detail.data.totals.approved_lkr_cents, { whole: true })}
                emphasis="quiet"
                footer={formatCount(detail.data.totals.approved_count)}
              />
              <Figure
                label={t('metricDisbursed')}
                value={formatLKR(detail.data.totals.disbursed_lkr_cents, { whole: true })}
                context={t('disbursements')}
                emphasis="quiet"
                footer={formatCount(detail.data.totals.disbursed_count)}
              />
              <Figure
                label={t('metricMedianDays')}
                value={formatDays(summary?.median_days_to_disbursement ?? null)}
                emphasis="quiet"
                // The median comes from the district endpoint, not from the DS breakdown.
                // A median of the per-division medians is not the district median, and
                // averaging them would publish a figure nobody's data supports.
                context={t('slowTitle')}
              />
            </div>

            {detail.data.totals.disbursed_count === 0 ? (
              <p className="mt-4 max-w-prose rounded-[var(--radius-default)] border border-[var(--pending)] bg-[var(--surface-card)] p-3 text-sm">
                {t('noDisbursements')}
              </p>
            ) : null}

            <div className="mt-6">
              <ScrollableTable label={t('dsDivision')}>
                <table className="w-full border-collapse text-sm">
                  <caption className="px-3 py-2 text-left text-xs text-[var(--text-muted)]">
                    {districtName} — {t('dsDivision')}
                  </caption>
                  <thead>
                    <tr className="bg-[var(--surface-raised)] text-left">
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t('dsDivision')}
                      </th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">
                        {t('metricAssessed')}
                      </th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">
                        {t('assessedHouseholds')}
                      </th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">
                        {t('metricApproved')}
                      </th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">
                        {t('metricDisbursed')}
                      </th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">
                        {t('disbursements')}
                      </th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">
                        {t('confirmationRate')}
                      </th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">
                        {t('medianDays')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.data.divisions.map((row) => (
                      <tr key={row.ds_division_code} className="border-t border-[var(--divider)]">
                        <th scope="row" className="px-3 py-2 text-left font-normal">
                          {localisedName(
                            dsNames.get(row.ds_division_code),
                            locale,
                            row.ds_division_code,
                          )}
                          <span
                            className="block text-2xs text-[var(--text-muted)]"
                            title={row.ds_division_code}
                          >
                            {shortDsCode(row.ds_division_code)}
                          </span>
                        </th>
                        <td data-sarana-datum="" className="px-3 py-2 text-right">
                          {formatLKR(row.assessed_lkr_cents, { whole: true })}
                        </td>
                        <td data-sarana-datum="" className="px-3 py-2 text-right">
                          {formatCount(row.assessed_households)}
                        </td>
                        <td data-sarana-datum="" className="px-3 py-2 text-right">
                          {formatLKR(row.approved_lkr_cents, { whole: true })}
                        </td>
                        <td data-sarana-datum="" className="px-3 py-2 text-right">
                          {formatLKR(row.disbursed_lkr_cents, { whole: true })}
                        </td>
                        <td data-sarana-datum="" className="px-3 py-2 text-right">
                          {formatCount(row.disbursed_count)}
                        </td>
                        <td data-sarana-datum="" className="px-3 py-2 text-right">
                          {formatPercent(
                            row.disbursed_count > 0
                              ? row.confirmed_count / row.disbursed_count
                              : null,
                          )}
                        </td>
                        <td data-sarana-datum="" className="px-3 py-2 text-right">
                          {formatDays(row.median_days_to_disbursement)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t-2 border-[var(--divider)] bg-[var(--surface-raised)] font-medium">
                      <th scope="row" className="px-3 py-2 text-left">
                        {common('total')}
                      </th>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatLKR(detail.data.totals.assessed_lkr_cents, { whole: true })}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatCount(detail.data.totals.assessed_households)}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatLKR(detail.data.totals.approved_lkr_cents, { whole: true })}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatLKR(detail.data.totals.disbursed_lkr_cents, { whole: true })}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatCount(detail.data.totals.disbursed_count)}
                      </td>
                      <td className="px-3 py-2 text-right">—</td>
                      <td className="px-3 py-2 text-right">—</td>
                    </tr>
                  </tfoot>
                </table>
              </ScrollableTable>
            </div>

            {/* Stated, counted and totalled. Never a silent gap. */}
            {detail.data.suppressed_divisions > 0 ? (
              <section
                aria-labelledby="suppressed"
                className="mt-4 max-w-prose rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-4"
              >
                <h2
                  id="suppressed"
                  className="m-0 text-base font-semibold text-[var(--text-primary)]"
                >
                  {t('suppressedTitle', { count: detail.data.suppressed_divisions })}
                </h2>
                <p className="mt-2 text-sm text-[var(--text-muted)]">
                  {t('suppressedAmount', {
                    amount: formatLKR(detail.data.suppressed_lkr_cents, { whole: true }),
                    disbursements: formatCount(detail.data.suppressed_disbursements),
                  })}
                </p>
                <p className="mt-2 text-xs text-[var(--text-muted)]">
                  {methodology('privacyBody')}
                </p>
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  {methodology('privacyZero')}
                </p>
              </section>
            ) : null}

            <AsOf
              when={detail.data.as_of}
              locale={locale}
              label={(when) => common('asOf', { when })}
            />
          </>
        )}
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
