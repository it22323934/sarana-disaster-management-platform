/**
 * `/anchors` — the published Merkle roots and their Object Lock URIs.
 *
 * The one page whose most important content is a thing that may not exist. When no object
 * store is configured the platform writes no URI and logs that it has not, and this page
 * says so at the top rather than showing a column of empty cells. An anchors page that
 * looked complete while the external half was missing would be the exact overclaim the
 * `/verify` page warns against.
 */

import { setRequestLocale, getTranslations } from 'next-intl/server';
import type { Metadata } from 'next';

import { formatDate, formatDateTime } from '@sarana/ts-shared/format';
import type { Locale } from '@sarana/ts-shared/i18n';

import { PageShell, SiteFooter, SiteHeader } from '../../../src/components/chrome';
import { Hash, ReadFailure, ScrollableTable } from '../../../src/components/provenance';
import { formatCount } from '../../../src/lib/format';
import { getAnchors } from '../../../src/lib/public-api';

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
  const t = await getTranslations({ locale, namespace: 'anchors' });
  return { title: t('title'), description: t('lead') };
}

export default async function AnchorsPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: Locale }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: 'anchors' });
  const errors = await getTranslations({ locale, namespace: 'errors' });

  const anchors = await getAnchors();

  // The external anchor is either in place for every day or it is not in place at all, and
  // the honest headline is the pessimistic one: if any published day lacks a storage URI,
  // the guarantee that survives an operator rewriting the database has a hole in it.
  const anyUnwritten = anchors.ok
    ? anchors.data.anchors.some((anchor) => anchor.s3_object_lock_uri === null)
    : false;

  return (
    <>
      <SiteHeader locale={locale} pathname="/anchors" />
      <PageShell title={t('title')} lead={t('lead')}>
        {!anchors.ok ? (
          <ReadFailure
            reason={anchors.reason}
            title={errors('title')}
            explanation={errors(anchors.reason)}
            whatToDo={errors('whatToDo')}
            neverZero={errors('neverZero')}
          />
        ) : (
          <>
            {anyUnwritten ? (
              <section
                aria-labelledby="not-written"
                className="mb-6 max-w-prose rounded-[var(--radius-default)] border border-[var(--pending)] bg-[var(--surface-card)] p-4"
              >
                <h2
                  id="not-written"
                  className="m-0 text-base font-semibold text-[var(--text-primary)]"
                >
                  {t('notWrittenTitle')}
                </h2>
                <p className="mt-2 text-sm text-[var(--text-muted)]">{t('notWrittenBody')}</p>
              </section>
            ) : null}

            {anchors.data.anchors.length === 0 ? (
              <p className="text-sm text-[var(--text-muted)]">{t('noAnchors')}</p>
            ) : (
              <ScrollableTable label={t('title')}>
                <table className="w-full border-collapse text-sm">
                  <caption className="sr-only">{t('lead')}</caption>
                  <thead>
                    <tr className="bg-[var(--surface-raised)] text-left">
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t('date')}
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t('merkleRoot')}
                      </th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">
                        {t('entries')}
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t('range')}
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t('prevAnchor')}
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t('objectLock')}
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t('published')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {anchors.data.anchors.map((anchor) => (
                      <tr key={anchor.date} className="border-t border-[var(--divider)]">
                        <th scope="row" className="whitespace-nowrap px-3 py-2 text-left font-normal">
                          <time dateTime={anchor.date}>{formatDate(anchor.date, locale)}</time>
                        </th>
                        <td className="px-3 py-2">
                          <Hash value={anchor.merkle_root} />
                        </td>
                        <td data-sarana-datum="" className="px-3 py-2 text-right">
                          {formatCount(anchor.entry_count)}
                        </td>
                        <td data-sarana-datum="" className="whitespace-nowrap px-3 py-2">
                          {anchor.first_seq}–{anchor.last_seq}
                        </td>
                        <td className="px-3 py-2">
                          {anchor.prev_anchor_hash ? (
                            <Hash value={anchor.prev_anchor_hash} showChars={12} />
                          ) : (
                            // The genesis day has nothing before it. An em dash rather
                            // than sixty-four zeroes, which would read as a real hash.
                            '—'
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {anchor.s3_object_lock_uri ? (
                            <code className="font-mono text-2xs break-all">
                              {anchor.s3_object_lock_uri}
                            </code>
                          ) : (
                            <span className="text-[var(--pending)]">{t('notWritten')}</span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">
                          {anchor.published_at ? (
                            <time dateTime={anchor.published_at}>
                              {formatDateTime(anchor.published_at, locale)}
                            </time>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollableTable>
            )}

            <section aria-labelledby="chain" className="mt-8 max-w-prose">
              <h2 id="chain" className="m-0 text-lg font-semibold text-[var(--text-primary)]">
                {t('chainTitle')}
              </h2>
              <p className="mt-2 text-sm text-[var(--text-muted)]">{t('chainBody')}</p>
            </section>

            {/* The hashing rules travel with the anchors, so a verifier does not have to
                read this repository to reproduce a root. Rendered rather than linked for
                the same reason the API attaches them to the response. */}
            <section aria-labelledby="scheme" className="mt-8">
              <h2 id="scheme" className="m-0 text-lg font-semibold text-[var(--text-primary)]">
                {t('merkleRoot')}
              </h2>
              <dl className="mt-3 grid grid-cols-1 gap-2 text-sm">
                {Object.entries(anchors.data.scheme).map(([key, value]) => (
                  <div key={key} className="flex flex-col gap-0.5">
                    <dt className="font-mono text-2xs text-[var(--text-muted)]">{key}</dt>
                    <dd className="m-0 break-words font-mono text-xs text-[var(--text-primary)]">
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          </>
        )}
      </PageShell>
      <SiteFooter locale={locale} />
    </>
  );
}
