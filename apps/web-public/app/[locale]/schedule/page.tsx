/**
 * `/schedule` — every cost schedule version, with the formula verbatim and a worked example.
 *
 * The brief asks for this to be the most readable page on the site, and the reason is
 * specific: it is what turns "your entitlement is Rs. 340,000" from an assertion into
 * something a household can check against their own damage. Someone reading it may be
 * doing so because they think the figure they were given is wrong.
 *
 * So the layout is a definition list per line rather than a wide table. A rate table with
 * eight columns is readable on a laptop and unreadable on the phone most of its readers
 * hold, and this is the one page where losing the reader means they cannot check the thing
 * the whole site exists to let them check.
 *
 * **The formula is rendered verbatim, as stored.** It is a JSON object in the database, and
 * it is printed as JSON rather than prettified into prose. A paraphrase is a second
 * definition that can drift from the one the calculator uses, and the reader checking their
 * own arithmetic needs the one the calculator uses.
 */

import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import { formatDate } from '@sarana/ts-shared/format';
import type { Locale } from '@sarana/ts-shared/i18n';

import { PageShell, SiteFooter, SiteHeader } from '../../../src/components/chrome';
import { ReadFailure } from '../../../src/components/provenance';
import { formatLKR, localisedName } from '../../../src/lib/format';
import { getCostSchedules, type CostSchedule, type ScheduleLine } from '../../../src/lib/public-api';

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
  const t = await getTranslations({ locale, namespace: 'schedule' });
  return { title: t('title'), description: t('lead') };
}

/**
 * Whether a schedule is the one in force today.
 *
 * Computed from the effective dates rather than taken from a flag, because the API does
 * not publish one and inferring it here keeps the page honest about a schedule that has
 * expired with no replacement — which shows as no version in force rather than as the
 * newest one being current.
 */
function inForce(schedule: CostSchedule, today: string): boolean {
  return (
    schedule.effective_from <= today &&
    (schedule.effective_to === null || schedule.effective_to > today)
  );
}

/**
 * A worked example for one line, on a synthetic household.
 *
 * Quantity two, chosen because it is the smallest number that makes the multiplication
 * visible — a quantity of one renders `rate × 1 = rate`, which demonstrates nothing about
 * how the calculation works. The cap is applied here exactly as the calculator applies it,
 * so a reader who follows the arithmetic and hits the cap sees the cap win, which is the
 * step that surprises people.
 */
function workedExample(line: ScheduleLine): {
  readonly quantity: number;
  readonly gross: number;
  readonly capped: boolean;
  readonly result: number;
} {
  const quantity = 2;
  const gross = line.rate_lkr_cents * quantity;
  const capped = line.cap_lkr_cents !== null && gross > line.cap_lkr_cents;
  return { quantity, gross, capped, result: capped ? (line.cap_lkr_cents as number) : gross };
}

export default async function SchedulePage({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: 'schedule' });
  const errors = await getTranslations({ locale, namespace: 'errors' });

  const schedules = await getCostSchedules();
  // Compared as ISO date strings, which sort lexicographically. Colombo rather than UTC:
  // a schedule that comes into force on the 1st does so at midnight in Sri Lanka.
  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Colombo' });

  return (
    <>
      <SiteHeader locale={locale} pathname="/schedule" />
      <PageShell title={t('title')} lead={t('lead')}>
        {!schedules.ok ? (
          <ReadFailure
            reason={schedules.reason}
            title={errors('title')}
            explanation={errors(schedules.reason)}
            whatToDo={errors('whatToDo')}
            neverZero={errors('neverZero')}
          />
        ) : schedules.data.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">{t('noSchedules')}</p>
        ) : (
          <div className="flex flex-col gap-10">
            {schedules.data.map((schedule) => {
              const current = inForce(schedule, today);
              return (
                <section
                  key={schedule.id}
                  aria-labelledby={`schedule-${schedule.id}`}
                  className="rounded-[var(--radius-surface)] border border-[var(--divider)] p-4"
                >
                  <div className="flex flex-wrap items-baseline gap-3">
                    <h2
                      id={`schedule-${schedule.id}`}
                      className="m-0 text-xl font-semibold text-[var(--text-primary)]"
                    >
                      {t('version', { version: schedule.version })}
                    </h2>
                    <span
                      className={
                        current
                          ? 'rounded-[var(--radius-cell)] border border-[var(--verified)] px-2 py-0.5 text-2xs font-medium text-[var(--verified)]'
                          : 'rounded-[var(--radius-cell)] border border-[var(--divider)] px-2 py-0.5 text-2xs text-[var(--text-muted)]'
                      }
                    >
                      {current ? t('inForce') : t('superseded')}
                    </span>
                  </div>

                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    {schedule.effective_to
                      ? t('effective', {
                          from: formatDate(schedule.effective_from, locale),
                          to: formatDate(schedule.effective_to, locale),
                        })
                      : t('effectiveOpen', { from: formatDate(schedule.effective_from, locale) })}
                    {' · '}
                    {t('publishedAt', { when: formatDate(schedule.published_at, locale) })}
                  </p>
                  <p className="mt-1 text-xs text-[var(--text-muted)]">
                    {schedule.source_ref
                      ? t('sourceRef', { ref: schedule.source_ref })
                      : t('noSource')}
                  </p>

                  <div className="mt-5 flex flex-col gap-5">
                    {schedule.lines.map((line) => {
                      const example = workedExample(line);
                      return (
                        <article
                          key={line.id}
                          className="rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-4"
                        >
                          <h3 className="m-0 text-base font-semibold text-[var(--text-primary)]">
                            {localisedName(line.description, locale, line.category)}
                          </h3>
                          <p className="mt-1 text-xs text-[var(--text-muted)]">
                            {t('category')}: {line.category}
                            {line.subcategory ? ` · ${t('subcategory')}: ${line.subcategory}` : ''}
                          </p>

                          <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                            <div>
                              <dt className="text-xs text-[var(--text-muted)]">{t('rate')}</dt>
                              <dd data-sarana-datum="" className="m-0 font-medium">
                                {formatLKR(line.rate_lkr_cents)} / {line.unit}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-xs text-[var(--text-muted)]">{t('cap')}</dt>
                              <dd data-sarana-datum="" className="m-0 font-medium">
                                {line.cap_lkr_cents === null
                                  ? t('noCap')
                                  : formatLKR(line.cap_lkr_cents)}
                              </dd>
                            </div>
                          </dl>

                          <div className="mt-3">
                            <p className="m-0 text-xs text-[var(--text-muted)]">{t('formula')}</p>
                            {/* Verbatim, as stored. See this file's docstring. */}
                            <pre
                              role="region"
                              aria-label={t('formula')}
                              tabIndex={0}
                              className="mt-1 overflow-x-auto rounded-[var(--radius-cell)] bg-[var(--surface-raised)] p-3 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
                            >
                              <code>{JSON.stringify(line.formula, null, 2)}</code>
                            </pre>
                          </div>

                          <div className="mt-3 border-t border-[var(--divider)] pt-3">
                            <h4 className="m-0 text-sm font-semibold text-[var(--text-primary)]">
                              {t('workedTitle')}
                            </h4>
                            <p className="mt-1 text-xs text-[var(--text-muted)]">
                              {t('workedLead')}
                            </p>
                            <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                              <div className="flex justify-between gap-3">
                                <dt className="text-[var(--text-muted)]">
                                  {t('workedQuantity')}
                                </dt>
                                <dd data-sarana-datum="" className="m-0">
                                  {example.quantity} {line.unit}
                                </dd>
                              </div>
                              <div className="flex justify-between gap-3">
                                <dt className="text-[var(--text-muted)]">
                                  {t('workedCalculation')}
                                </dt>
                                <dd data-sarana-datum="" className="m-0">
                                  {formatLKR(example.gross)}
                                </dd>
                              </div>
                              {line.cap_lkr_cents !== null ? (
                                <div className="flex justify-between gap-3">
                                  <dt className="text-[var(--text-muted)]">
                                    {t('workedCapped')}
                                  </dt>
                                  <dd data-sarana-datum="" className="m-0">
                                    {formatLKR(line.cap_lkr_cents)}
                                  </dd>
                                </div>
                              ) : null}
                              <div className="flex justify-between gap-3 font-medium">
                                <dt>{t('workedResult')}</dt>
                                <dd data-sarana-datum="" className="m-0">
                                  {formatLKR(example.result)}
                                </dd>
                              </div>
                            </dl>
                            {example.capped ? (
                              <p className="mt-2 text-xs font-medium text-[var(--text-primary)]">
                                {t('capApplied')}
                              </p>
                            ) : null}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
