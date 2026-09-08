/**
 * `/districts` — the choropleth, the table, and "where is it slow".
 *
 * **The metric selector is a GET form with no JavaScript.** A `<select>` with an `onChange`
 * handler would be a client component and would stop working for exactly the reader the
 * brief names: the journalist behind a locked-down proxy. A form that submits to the same
 * route with `?metric=` works everywhere, is bookmarkable, and gives a shareable URL per
 * view — which matters more here than the saved click, because "the slow-payment map" is
 * a thing somebody wants to link to in a story.
 *
 * The `<noscript>`-free submit button is always rendered rather than hidden when scripting
 * is present. A control that disappears when JavaScript loads is a control a keyboard user
 * loses mid-interaction.
 *
 * The table comes before the map in the DOM. A choropleth is not accessible and is not
 * copy-pasteable, so the accessible, copyable thing is the one a screen reader and a
 * printer reach first.
 */

import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import type { Locale } from '@sarana/ts-shared/i18n';

import { PageShell, SiteFooter, SiteHeader } from '../../../src/components/chrome';
import { DistrictMap, type DistrictShade } from '../../../src/components/district-map';
import { AsOf, ReadFailure, ScrollableTable } from '../../../src/components/provenance';
import {
  formatCount,
  formatDays,
  formatLKR,
  formatPercent,
  formatRate,
  localisedName,
} from '../../../src/lib/format';
import { METRICS, metricById, normalise } from '../../../src/lib/metrics';
import {
  getAreaDistricts,
  getDistrictMetrics,
  nameIndex,
  type DistrictMetrics,
} from '../../../src/lib/public-api';

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
  const t = await getTranslations({ locale, namespace: 'districts' });
  return { title: t('title'), description: t('lead') };
}

/** Render one metric's value in the units it is measured in. */
function renderMetric(row: DistrictMetrics, kind: string, value: number | null): string {
  if (value === null) return '—';
  switch (kind) {
    case 'money':
      return formatLKR(value, { whole: true });
    case 'percent':
      return formatPercent(value);
    case 'days':
      return formatDays(value);
    default:
      return formatRate(value);
  }
}

export default async function DistrictsPage({
  params,
  searchParams,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
  readonly searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { locale } = await params;
  const query = await searchParams;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: 'districts' });
  const common = await getTranslations({ locale, namespace: 'common' });
  const errors = await getTranslations({ locale, namespace: 'errors' });

  const selected = metricById(typeof query['metric'] === 'string' ? query['metric'] : undefined);

  const [metrics, areas] = await Promise.all([getDistrictMetrics(), getAreaDistricts()]);
  const names = areas.ok ? nameIndex(areas.data.districts) : new Map();

  return (
    <>
      <SiteHeader locale={locale} pathname="/districts" />
      <PageShell title={t('title')} lead={t('lead')}>
        {!metrics.ok ? (
          <ReadFailure
            reason={metrics.reason}
            title={errors('title')}
            explanation={errors(metrics.reason)}
            whatToDo={errors('whatToDo')}
            neverZero={errors('neverZero')}
          />
        ) : (
          <>
            <form
              method="get"
              action={`/${locale}/districts`}
              data-print-hide
              className="mb-5 flex flex-wrap items-end gap-3 rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-3"
            >
              <div className="flex flex-col gap-1">
                <label htmlFor="metric" className="text-xs font-medium text-[var(--text-muted)]">
                  {t('metric')}
                </label>
                <select
                  id="metric"
                  name="metric"
                  defaultValue={selected.id}
                  className="min-h-[44px] rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-base)] px-3 py-2 text-sm text-[var(--text-primary)]"
                >
                  {METRICS.map((metric) => (
                    <option key={metric.id} value={metric.id}>
                      {t(metric.labelKey)}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="submit"
                className="min-h-[44px] rounded-[var(--radius-default)] bg-[var(--signal-500)] px-4 py-2 text-sm font-medium text-[var(--on-signal)]"
              >
                {t('metric')}
              </button>
            </form>

            <ScrollableTable label={t('tableCaption')}>
              <table className="w-full border-collapse text-sm">
                <caption className="px-3 py-2 text-left text-xs text-[var(--text-muted)]">
                  {t('tableCaption')} — {t(selected.labelKey)}
                </caption>
                <thead>
                  <tr className="bg-[var(--surface-raised)] text-left">
                    <th scope="col" className="px-3 py-2 font-medium">
                      {common('district')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      {t(selected.labelKey)}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      {t('assessedHouseholds')}
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
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      {t('grievanceRate')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.data.districts.map((row) => (
                    <tr key={row.district_code} className="border-t border-[var(--divider)]">
                      <th scope="row" className="px-3 py-2 text-left font-normal">
                        <a
                          href={`/${locale}/districts/${row.district_code}`}
                          className="text-[var(--text-accent)] underline"
                        >
                          {localisedName(names.get(row.district_code), locale, row.district_code)}
                        </a>
                        <span className="block text-2xs text-[var(--text-muted)]">
                          {row.district_code}
                        </span>
                      </th>
                      <td data-sarana-datum="" className="px-3 py-2 text-right font-medium">
                        {renderMetric(row, selected.kind, selected.value(row))}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatCount(row.assessed_households)}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatCount(row.disbursed_count)}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatPercent(row.confirmation_rate)}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatDays(row.median_days_to_disbursement)}
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatRate(row.grievance_rate_per_1000_disbursements)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollableTable>

            <AsOf
              when={metrics.data.as_of}
              locale={locale}
              label={(when) => common('asOf', { when })}
            />

            <section aria-labelledby="map" className="mt-8" data-print-hide>
              <h2 id="map" className="m-0 text-lg font-semibold text-[var(--text-primary)]">
                {t('mapTitle')}
              </h2>
              <p className="mt-1 max-w-prose text-sm text-[var(--text-muted)]">
                {t('mapUnavailable')}
              </p>
              <div className="mt-3">
                <DistrictMap
                  title={`${t('mapTitle')} — ${t(selected.labelKey)}`}
                  geojsonUrl="/api/public/districts.geojson"
                  noDataLabel={common('noData')}
                  generatedNote={t('mapGenerated')}
                  shades={metrics.data.districts.map<DistrictShade>((row) => ({
                    districtCode: row.district_code,
                    position: normalise(selected.value(row), metrics.data.districts, selected),
                    label: localisedName(names.get(row.district_code), locale, row.district_code),
                    value: renderMetric(row, selected.kind, selected.value(row)),
                  }))}
                />
              </div>
            </section>

            <section aria-labelledby="slow" className="mt-8 max-w-prose">
              <h2 id="slow" className="m-0 text-lg font-semibold text-[var(--text-primary)]">
                {t('slowTitle')}
              </h2>
              <p className="mt-2 text-sm text-[var(--text-muted)]">{t('slowBody')}</p>
              <p className="mt-3 text-sm" data-print-hide>
                <a
                  href={`/${locale}/districts?metric=medianDays`}
                  className="text-[var(--text-accent)] underline"
                >
                  {t('metricMedianDays')}
                </a>
              </p>
            </section>
          </>
        )}
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
