/**
 * `/methodology` — how each number is produced, what is simulated, and what is wrong with us.
 *
 * The simulated-data statement is the first thing on the page, unambiguously and at the
 * top, because that is what the brief requires and because a viewer who leaves this site
 * believing these figures describe real disbursements has been misled by us regardless of
 * what a badge in the header said.
 *
 * The limitations section publishes error rates the platform has not measured well, and
 * says which. Two of them are absences rather than numbers — per-language speech
 * recognition accuracy, and the anomaly detector's operational false-positive rate — and
 * both are stated as absences. An invented accuracy figure for Tamil would be worse than
 * none, because it would be quoted.
 */

import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import type { Locale } from '@sarana/ts-shared/i18n';

import { PageShell, SiteFooter, SiteHeader } from '../../../src/components/chrome';

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
  const t = await getTranslations({ locale, namespace: 'methodology' });
  return { title: t('title'), description: t('simulatedTitle') };
}

function Section({
  id,
  title,
  children,
}: {
  readonly id: string;
  readonly title: string;
  readonly children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="border-t border-[var(--divider)] pt-6">
      <h2 id={id} className="m-0 text-lg font-semibold text-[var(--text-primary)]">
        {title}
      </h2>
      <div className="mt-2 max-w-prose text-sm text-[var(--text-muted)]">{children}</div>
    </section>
  );
}

export default async function MethodologyPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: 'methodology' });
  const nav = await getTranslations({ locale, namespace: 'nav' });

  return (
    <>
      <SiteHeader locale={locale} pathname="/methodology" />
      <PageShell title={t('title')}>
        {/* Top of the page, bordered, not a footnote. The one statement that must reach a
            reader who reads nothing else. */}
        <section
          aria-labelledby="simulated"
          className="mb-8 max-w-prose rounded-[var(--radius-surface)] border-2 border-[var(--sev-2-border)] bg-[var(--sev-2-bg)] p-5"
        >
          <h2 id="simulated" className="m-0 text-xl font-semibold text-[var(--sev-2-fg)]">
            {t('simulatedTitle')}
          </h2>
          <p className="mt-3 text-sm text-[var(--text-primary)]">{t('simulatedBody')}</p>
          <p className="mt-3 text-sm text-[var(--text-primary)]">{t('simulatedWhy')}</p>
        </section>

        <div className="flex flex-col gap-6">
          <Section id="numbers" title={t('numbersTitle')}>
            <ul className="m-0 list-disc pl-5">
              <li>{t('assessedHow')}</li>
              <li className="mt-2">{t('approvedHow')}</li>
              <li className="mt-2">{t('disbursedHow')}</li>
              <li className="mt-2">{t('confirmedHow')}</li>
            </ul>
            <p className="mt-3">
              <a href={`/${locale}/schedule`} className="text-[var(--text-accent)] underline">
                {nav('schedule')}
              </a>
            </p>
          </Section>

          <Section id="privacy" title={t('privacyTitle')}>
            <p className="m-0">{t('privacyBody')}</p>
            <p className="mt-3">{t('privacyZero')}</p>
          </Section>

          <Section id="boundaries" title={t('boundariesTitle')}>
            <p className="m-0">{t('boundariesBody')}</p>
          </Section>

          <Section id="freshness" title={t('freshnessTitle')}>
            <p className="m-0">{t('freshnessBody')}</p>
          </Section>

          <Section id="sse" title={t('sseTitle')}>
            <p className="m-0">{t('sseBody')}</p>
          </Section>

          <Section id="limits" title={t('limitsTitle')}>
            <p className="m-0 font-medium text-[var(--text-primary)]">{t('limitsLead')}</p>

            <h3 className="mt-4 text-base font-semibold text-[var(--text-primary)]">
              {t('asrTitle')}
            </h3>
            <p className="mt-1">{t('asrBody')}</p>

            <h3 className="mt-4 text-base font-semibold text-[var(--text-primary)]">
              {t('anomalyTitle')}
            </h3>
            <p className="mt-1">{t('anomalyBody')}</p>

            <h3 className="mt-4 text-base font-semibold text-[var(--text-primary)]">
              {t('anchorTitle')}
            </h3>
            <p className="mt-1">{t('anchorBody')}</p>
            <p className="mt-2">
              <a href={`/${locale}/anchors`} className="text-[var(--text-accent)] underline">
                {nav('anchors')}
              </a>
            </p>
          </Section>

          <Section id="contact" title={t('contactTitle')}>
            <p className="m-0">{t('contactBody')}</p>
            <p className="mt-3">
              <a href={`/${locale}/grievances`} className="text-[var(--text-accent)] underline">
                {nav('grievances')}
              </a>
            </p>
          </Section>
        </div>
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
