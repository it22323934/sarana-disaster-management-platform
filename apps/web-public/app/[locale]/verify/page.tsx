/**
 * `/verify` — the page that makes the central claim checkable.
 *
 * Six steps, in the order somebody actually does them, written for a competent
 * non-specialist with no cryptography background.
 *
 * **The `curl` commands are generated from the same constants the app fetches with**, not
 * typed into the catalogue as prose. `scripts/verify-page-examples.sh` executes exactly
 * these commands against a running instance and is one of the Definition of Done gates, so
 * a snippet that drifts from the real endpoint fails CI rather than wasting a reader's
 * afternoon. The commands appear in `<code>` blocks whose text content the script extracts.
 *
 * **Step 6 is the one that must not be softened.** Overclaiming what a hash chain proves is
 * the fastest way to lose a technically literate critic, and this platform's claim is
 * narrow: the record has not been altered since it was anchored. It says nothing about
 * whether the original assessment was right. The two halves are given equal space and the
 * limitation is not in a footnote.
 */

import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import { formatDate } from '@sarana/ts-shared/format';
import type { Locale } from '@sarana/ts-shared/i18n';

import { PageShell, SiteFooter, SiteHeader } from '../../../src/components/chrome';
import { Figure } from '../../../src/components/provenance';
import { formatCount } from '../../../src/lib/format';
import { getAnchors, getFunnel } from '../../../src/lib/public-api';
import { publicUrl } from '../../../src/lib/services';

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
  const t = await getTranslations({ locale, namespace: 'verify' });
  return { title: t('title'), description: t('lead') };
}

/**
 * A copy-pasteable command.
 *
 * `data-verify-command` is what `scripts/verify-page-examples.sh` looks for. The marker is
 * on the element rather than the script matching a code fence, so a command can be
 * reformatted without breaking the gate, and a code block that is *not* meant to be
 * executed — the expected output — is simply not marked.
 */
function Command({ children, label }: { readonly children: string; readonly label: string }) {
  return (
    <pre
      // Focusable and named for the same reason `ScrollableTable` is: a `<pre>` that
      // scrolls sideways cannot be scrolled by keyboard unless it can hold focus, and a
      // command a reader is told to copy is the last thing that should be unreachable.
      role="region"
      aria-label={label}
      tabIndex={0}
      className="mt-2 overflow-x-auto rounded-[var(--radius-cell)] border border-[var(--divider)] bg-[var(--surface-raised)] p-3 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
    >
      <code data-verify-command>{children}</code>
    </pre>
  );
}

function Output({ children, label }: { readonly children: string; readonly label: string }) {
  return (
    <pre
      role="region"
      aria-label={label}
      tabIndex={0}
      className="mt-2 overflow-x-auto rounded-[var(--radius-cell)] border border-[var(--divider)] bg-[var(--surface-raised)] p-3 text-xs text-[var(--text-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
    >
      <code>{children}</code>
    </pre>
  );
}

function Step({
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

export default async function VerifyPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: 'verify' });
  const nav = await getTranslations({ locale, namespace: 'nav' });

  const [anchors, funnel] = await Promise.all([getAnchors(), getFunnel()]);

  // The real upstream URLs, so the commands a reader copies are the ones this app uses.
  const feedUrl = publicUrl('ledger-svc', 'ledger/public');
  const anchorsUrl = publicUrl('ledger-svc', 'ledger/anchors');

  return (
    <>
      <SiteHeader locale={locale} pathname="/verify" />
      <PageShell title={t('title')} lead={t('lead')}>
        {/* The current state of the chain, so a reader can tell what they are about to
            verify before they spend five minutes on it. */}
        <section aria-labelledby="state" className="mb-8">
          <h2 id="state" className="m-0 text-lg font-semibold text-[var(--text-primary)]">
            {t('chainStatus')}
          </h2>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Figure
              label={t('entriesPublished')}
              value={funnel.ok ? formatCount(funnel.data.disbursed.count) : '—'}
              emphasis="quiet"
            />
            <Figure
              label={t('daysAnchored')}
              value={anchors.ok ? formatCount(anchors.data.anchors.length) : '—'}
              emphasis="quiet"
            />
            <Figure
              label={t('latestAnchor')}
              value={
                anchors.ok && anchors.data.anchors[0]
                  ? formatDate(anchors.data.anchors[0].date, locale)
                  : '—'
              }
              emphasis="quiet"
            />
          </div>
        </section>

        <div className="flex flex-col gap-6">
          <Step id="step1" title={t('step1Title')}>
            <p className="m-0">{t('step1Body')}</p>
            <p className="mt-3">{t('step1Body2')}</p>
            <p className="mt-3">{t('step1Body3')}</p>
          </Step>

          <Step id="step2" title={t('step2Title')}>
            <p className="m-0">{t('step2Body')}</p>
            <p className="mt-3">{t('step2Body2')}</p>
            <p className="mt-3">
              <a href={`/${locale}/anchors`} className="text-[var(--text-accent)] underline">
                {nav('anchors')}
              </a>
            </p>
          </Step>

          <Step id="step3" title={t('step3Title')}>
            <p className="m-0">{t('step3Body')}</p>
            <Command label={t('copyLabel')}>{`curl -s '${feedUrl}?from_seq=0&limit=5'`}</Command>
            <Command label={t('copyLabel')}>{`curl -s '${anchorsUrl}?limit=5'`}</Command>
          </Step>

          <Step id="step4" title={t('step4Title')}>
            <p className="m-0">{t('step4Body')}</p>
            <Command label={t('copyLabel')}>{`python tools/sarana-verify/verify.py --feed '${feedUrl}' --anchors '${anchorsUrl}'`}</Command>
            <p className="mt-4 font-medium text-[var(--text-primary)]">{t('step4Expected')}</p>
            <Output label={t('step4Expected')}>{`chain: OK (N entries, genesis to seq N)
anchors: OK (D days, each chained to the previous)
result: the published record is internally consistent`}</Output>
          </Step>

          <Step id="step5" title={t('step5Title')}>
            <p className="m-0">{t('step5Body')}</p>
            <Output label={t('step5Title')}>{`chain: FAILED at seq 4182
  expected prev_hash 9f2c… (from seq 4181)
  found    prev_hash 41ab…
result: entry 4182 does not follow entry 4181`}</Output>
            <p className="mt-3">{t('step5Contact')}</p>
            <p className="mt-2">
              <a href={`/${locale}/grievances`} className="text-[var(--text-accent)] underline">
                {nav('grievances')}
              </a>
            </p>
          </Step>

          <Step id="step6" title={t('step6Title')}>
            {/* Two paragraphs, same size, same weight. The limitation is not smaller than
                the claim. */}
            <p className="m-0 font-medium text-[var(--text-primary)]">{t('step6Proves')}</p>
            <p className="mt-3 font-medium text-[var(--text-primary)]">{t('step6NotProves')}</p>
            <p className="mt-3">{t('step6Body')}</p>
            <p className="mt-3">
              <a href={`/${locale}/grievances`} className="text-[var(--text-accent)] underline">
                {t('grievanceLink')}
              </a>
            </p>
          </Step>
        </div>

        {/*
          The shapes this site refuses to publish, shown so a reader can see what is being
          withheld. Marked `data-sarana-pii-example` so the PII sweep strips it: these are
          placeholders, and without the marker the sweep would flag the page that explains
          the sweep.
        */}
        <section
          aria-labelledby="withheld"
          className="mt-10 max-w-prose rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-4"
        >
          <h2 id="withheld" className="m-0 text-base font-semibold text-[var(--text-primary)]">
            {t('step6Title')}
          </h2>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            {t('step6NotProves')}
          </p>
          <ul className="mt-3 list-disc pl-5 text-sm text-[var(--text-muted)]">
            <li data-sarana-pii-example>NIC: 999999999999 / 111111111V</li>
            <li data-sarana-pii-example>Coordinate: 7.11111, 80.22222</li>
          </ul>
        </section>
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
