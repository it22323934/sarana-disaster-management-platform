/**
 * `/ledger` — the anonymised entry feed.
 *
 * Cursor paginated by `seq`, never by date, and the link buttons are plain `<a>` elements
 * carrying `?from_seq=`. That is the same reasoning the API applies: a verifier walking the
 * chain needs it unbroken, and a date filter would produce gaps it could not tell apart
 * from removed entries — which is the alarm the chain exists to raise.
 *
 * Pagination as links rather than a client-side control means each page has its own URL, so
 * an auditor can cite "entries 4,000 to 4,200" in a footnote and anyone can open it.
 */

import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import { formatDateTime } from '@sarana/ts-shared/format';
import type { Locale } from '@sarana/ts-shared/i18n';

import { PageShell, SiteFooter, SiteHeader } from '../../../src/components/chrome';
import { Hash, ReadFailure, ScrollableTable } from '../../../src/components/provenance';
import { formatCount, formatLKR } from '../../../src/lib/format';
import { getLedgerPage } from '../../../src/lib/public-api';

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

/**
 * Rows per page.
 *
 * Two hundred. Enough that scrolling is worth doing and few enough that the HTML stays
 * inside a size a 3G connection renders promptly — each row carries two 64-character
 * hashes, so the payload is dominated by them rather than by the money.
 */
const PAGE_SIZE = 200;

export async function generateMetadata({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'ledger' });
  return { title: t('title'), description: t('lead') };
}

function parseSeq(value: string | string[] | undefined): number {
  const raw = typeof value === 'string' ? Number.parseInt(value, 10) : Number.NaN;
  return Number.isFinite(raw) && raw >= 0 ? raw : 0;
}

export default async function LedgerPage({
  params,
  searchParams,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
  readonly searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { locale } = await params;
  const query = await searchParams;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: 'ledger' });
  const common = await getTranslations({ locale, namespace: 'common' });
  const errors = await getTranslations({ locale, namespace: 'errors' });

  const fromSeq = parseSeq(query['from_seq']);
  const page = await getLedgerPage(fromSeq, PAGE_SIZE);

  const first = page.ok ? page.data.entries[0] : undefined;
  const last = page.ok ? page.data.entries[page.data.entries.length - 1] : undefined;
  const previousSeq = Math.max(0, fromSeq - PAGE_SIZE);

  return (
    <>
      <SiteHeader locale={locale} pathname="/ledger" />
      <PageShell
        title={t('title')}
        lead={t('lead')}
        actions={
          <>
            <a
              href={`/api/public/ledger?from_seq=${fromSeq}&limit=${PAGE_SIZE}&format=csv`}
              className="text-sm text-[var(--text-accent)] underline"
              download
            >
              {common('downloadCsv')}
            </a>
            <a
              href={`/api/public/ledger?from_seq=${fromSeq}&limit=${PAGE_SIZE}`}
              className="text-sm text-[var(--text-accent)] underline"
            >
              {common('downloadJson')}
            </a>
          </>
        }
      >
        {!page.ok ? (
          <ReadFailure
            reason={page.reason}
            title={errors('title')}
            explanation={errors(page.reason)}
            whatToDo={errors('whatToDo')}
            neverZero={errors('neverZero')}
          />
        ) : page.data.entries.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">{t('noEntries')}</p>
        ) : (
          <>
            <ScrollableTable label={t('title')}>
              <table className="w-full border-collapse text-sm">
                <caption className="px-3 py-2 text-left text-xs text-[var(--text-muted)]">
                  {t('showingRange', { from: first?.seq ?? 0, to: last?.seq ?? 0 })}
                </caption>
                <thead>
                  <tr className="bg-[var(--surface-raised)] text-left">
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t('seq')}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t('date')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      {t('amount')}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t('rail')}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t('reference')}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t('entryHash')}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t('anchorDate')}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      {t('state')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {page.data.entries.map((entry) => (
                    <tr key={entry.seq} className="border-t border-[var(--divider)]">
                      <th scope="row" data-sarana-datum="" className="px-3 py-2 text-left font-normal">
                        {entry.seq}
                      </th>
                      <td className="whitespace-nowrap px-3 py-2">
                        <time dateTime={entry.released_at}>
                          {formatDateTime(entry.released_at, locale)}
                        </time>
                      </td>
                      <td data-sarana-datum="" className="px-3 py-2 text-right">
                        {formatLKR(entry.amount_lkr_cents)}
                      </td>
                      <td className="px-3 py-2">{entry.payment_rail}</td>
                      <td data-sarana-datum="" className="px-3 py-2 font-mono text-2xs">
                        {entry.payment_ref ?? '—'}
                      </td>
                      <td className="px-3 py-2">
                        {entry.entry_hash ? <Hash value={entry.entry_hash} /> : '—'}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">{entry.anchor_date}</td>
                      <td className="px-3 py-2">
                        {/* The returned state is a word, not only a colour. A row that
                            differed from its neighbours by background alone would be
                            invisible in greyscale and to a colour-blind reader. */}
                        {entry.reversed ? (
                          <span className="font-medium text-[var(--pending)]">
                            {t('reversedFlag')}
                          </span>
                        ) : (
                          <span className="text-[var(--text-muted)]">{t('live')}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollableTable>

            <nav
              aria-label={t('title')}
              data-print-hide
              className="mt-4 flex items-center justify-between gap-4"
            >
              <span className="text-xs text-[var(--text-muted)]">
                {common('showing', {
                  count: formatCount(page.data.entries.length),
                  total: formatCount(page.data.entries.length),
                })}
              </span>
              <span className="flex gap-3">
                {fromSeq > 0 ? (
                  <a
                    href={`/${locale}/ledger?from_seq=${previousSeq}`}
                    className="text-sm text-[var(--text-accent)] underline"
                  >
                    {common('previous')}
                  </a>
                ) : null}
                {page.data.next_seq !== null ? (
                  <a
                    href={`/${locale}/ledger?from_seq=${page.data.next_seq}`}
                    className="text-sm text-[var(--text-accent)] underline"
                  >
                    {common('next')}
                  </a>
                ) : null}
              </span>
            </nav>

            <p className="mt-4 max-w-prose text-xs text-[var(--text-muted)]">
              {t('reversedNote')}
            </p>
          </>
        )}

        <section aria-labelledby="privacy" className="mt-8 max-w-prose">
          <h2 id="privacy" className="m-0 text-lg font-semibold text-[var(--text-primary)]">
            {t('privacyTitle')}
          </h2>
          <p className="mt-2 text-sm text-[var(--text-muted)]">{t('privacyBody')}</p>
        </section>

        <section aria-labelledby="export" className="mt-8 max-w-prose">
          <h2 id="export" className="m-0 text-lg font-semibold text-[var(--text-primary)]">
            {t('exportTitle')}
          </h2>
          <p className="mt-2 text-sm text-[var(--text-muted)]">{t('exportBody')}</p>
          <p className="mt-2 text-sm">
            <a
              href="/api/public/ledger"
              className="text-[var(--text-accent)] underline"
              data-print-url
            >
              {t('feedLink')}
            </a>{' '}
            <span className="text-xs text-[var(--text-muted)]">{common('openStandalone')}</span>
          </p>
        </section>
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
