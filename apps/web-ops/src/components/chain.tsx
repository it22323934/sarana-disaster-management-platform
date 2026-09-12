'use client';

/**
 * `/audit/chain` — recomputing the hash chain, and the anchors that make it checkable
 * from outside.
 *
 * The claim this platform makes is that a ledger entry cannot be edited after it is
 * written without that being detectable. This screen is where an auditor tests the claim
 * rather than reading it. Three things it has to get right:
 *
 * **A green result names its range.** "The chain is intact" over an unstated range is a
 * claim about nothing. Every result shows `from_seq`, `to_seq` and how many entries were
 * checked, so an auditor who verified 1-100 does not walk away believing they verified the
 * ledger.
 *
 * **A red result names the exact divergence.** `seq`, what was expected, what was found.
 * "The chain is broken" is not actionable; "entry 4,117 carries a prev_hash of X where the
 * previous entry hashes to Y" is.
 *
 * **The external anchor is reported as missing when it is.** The daily Merkle root is
 * computed, chained to the previous day and published — but `s3_object_lock_uri` is null
 * until an object store is wired, and that URI is the entire external half of the
 * guarantee. Without it the chain is verifiable against a database that the operator
 * controls, which is a much weaker claim, and this screen says so rather than showing a
 * green tick over an internally consistent record.
 */

import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  HashDisplay,
  Input,
  cn,
} from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useAnchors, verifyChain } from '../lib/queries';
import type { Anchor, VerifyResult } from '../lib/schemas';
import { ErrorPanel } from './degraded';

export function ChainVerification() {
  const t = useTranslations('chain');
  const common = useTranslations('common');

  const anchors = useAnchors();
  const [fromSeq, setFromSeq] = useState('');
  const [toSeq, setToSeq] = useState('');
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);

  async function verify(): Promise<void> {
    setBusy(true);
    setFailure(null);
    // Cleared before the call, so a stale green result cannot sit on screen while a new
    // range is being checked. An auditor glancing away and back must not read the old
    // answer as the new one.
    setResult(null);
    try {
      const from = fromSeq.trim() === '' ? undefined : Number(fromSeq);
      const to = toSeq.trim() === '' ? undefined : Number(toSeq);
      setResult(await verifyChain(from, to));
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  const rows = anchors.data?.anchors ?? [];
  const unanchored = rows.filter((anchor) => anchor.s3_object_lock_uri === null).length;

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">{t('title')}</h1>
        <p className="text-xs text-[var(--text-muted)]">{t('subtitle')}</p>
      </header>

      <section className="flex flex-col gap-3 rounded-[var(--radius-default)] border border-[var(--divider)] p-4">
        <h2 className="text-sm font-medium">{t('verifyRange')}</h2>
        <p className="text-xs text-[var(--text-muted)]">{t('verifyRangeHint')}</p>
        <div className="flex flex-wrap items-end gap-3">
          <Input
            label={t('fromSeq')}
            inputMode="numeric"
            datum
            value={fromSeq}
            onChange={(event) => setFromSeq(event.target.value.replace(/\D/g, ''))}
          />
          <Input
            label={t('toSeq')}
            inputMode="numeric"
            datum
            value={toSeq}
            onChange={(event) => setToSeq(event.target.value.replace(/\D/g, ''))}
          />
          <Button variant="primary" busy={busy} busyLabel={t('verify')} onClick={verify}>
            {t('verify')}
          </Button>
        </div>
      </section>

      {failure ? <ErrorPanel error={failure} /> : null}

      {result ? <VerifyResultPanel result={result} /> : null}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('anchors')}</h2>
        <p className="text-xs text-[var(--text-muted)]">{t('anchorsHint')}</p>

        {unanchored > 0 ? (
          // The honest headline. An internally consistent chain with no external anchor is
          // a weaker claim than it looks, and the difference is the whole point of the
          // anchor.
          <div
            className={cn(
              'rounded-[var(--radius-default)] border px-4 py-3',
              'border-[var(--sev-2-border)] bg-[var(--sev-2-bg)] text-[var(--sev-2-fg)]',
            )}
          >
            <p className="text-sm font-medium">{t('noExternalAnchor', { count: unanchored })}</p>
            <p className="mt-1 text-xs opacity-90">{t('noExternalAnchorHint')}</p>
          </div>
        ) : null}

        {anchors.data?.scheme && Object.keys(anchors.data.scheme).length > 0 ? (
          <dl className="rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-4">
            <h3 className="mb-2 text-2xs uppercase tracking-wide text-[var(--text-muted)]">
              {t('scheme')}
            </h3>
            {Object.entries(anchors.data.scheme).map(([key, value]) => (
              <div key={key} className="flex flex-wrap items-baseline gap-2 text-xs">
                <dt className="text-[var(--text-muted)]">{key}</dt>
                <dd data-sarana-datum="" className="font-mono">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}

        {anchors.isError ? (
          <ErrorPanel error={anchors.error} />
        ) : (
          <DataTable<Anchor>
            caption={t('anchors')}
            rows={rows}
            rowKey={(anchor) => anchor.date}
            height="24rem"
            empty={<EmptyState title={t('noAnchors')} description={t('noAnchorsHint')} />}
            columns={[
              {
                key: 'date',
                header: t('date'),
                width: '9rem',
                cell: (anchor) => (
                  <span data-sarana-datum="" className="font-mono text-xs">
                    {anchor.date}
                  </span>
                ),
              },
              {
                key: 'range',
                header: t('range'),
                width: '10rem',
                numeric: true,
                cell: (anchor) => (
                  <span data-sarana-datum="" className="font-mono text-xs">
                    {anchor.first_seq}–{anchor.last_seq}
                  </span>
                ),
              },
              {
                key: 'entries',
                header: t('entries'),
                width: '7rem',
                numeric: true,
                cell: (anchor) => (
                  <span data-sarana-datum="" className="font-mono">
                    {anchor.entry_count}
                  </span>
                ),
              },
              {
                key: 'root',
                header: t('merkleRoot'),
                cell: (anchor) => (
                  <HashDisplay
                    hash={anchor.merkle_root}
                    truncateTo={12}
                    copyLabel={common('copy')}
                    copiedLabel={common('copied')}
                  />
                ),
              },
              {
                key: 'external',
                header: t('externalAnchor'),
                width: '12rem',
                cell: (anchor) =>
                  anchor.s3_object_lock_uri === null ? (
                    <Badge tone="pending">{t('notAnchored')}</Badge>
                  ) : (
                    <Badge tone="verified">{t('anchored')}</Badge>
                  ),
              },
            ]}
          />
        )}
      </section>
    </div>
  );
}

/**
 * The verification result.
 *
 * Green or red, and in both cases the range. A result that said "intact" without saying
 * over what would let an auditor verify a hundred entries and report that the ledger is
 * sound.
 */
function VerifyResultPanel({ result }: { readonly result: VerifyResult }) {
  const t = useTranslations('chain');

  return (
    <section
      role="status"
      data-chain-intact={result.intact}
      className={cn(
        'flex flex-col gap-2 rounded-[var(--radius-default)] border px-4 py-3',
        result.intact
          ? 'border-[var(--verified)] text-[var(--verified)]'
          : 'border-[var(--sev-3-border)] bg-[var(--sev-3-bg)] text-[var(--sev-3-fg)]',
      )}
    >
      <p className="text-sm font-medium">{result.intact ? t('intact') : t('diverged')}</p>

      {/* The range, always. This is what stops a partial check being read as a whole one. */}
      <p data-sarana-datum="" className="font-mono text-xs">
        {t('checkedRange', {
          checked: result.checked,
          from: result.from_seq,
          to: result.to_seq,
        })}
      </p>

      {result.divergence ? (
        <dl className="mt-1 flex flex-col gap-1 text-xs">
          <div className="flex flex-wrap gap-2">
            <dt className="opacity-80">{t('divergenceAt')}</dt>
            <dd data-sarana-datum="" className="font-mono font-semibold">
              {result.divergence.seq}
            </dd>
          </div>
          <div className="flex flex-wrap gap-2">
            <dt className="opacity-80">{t('reason')}</dt>
            <dd>{result.divergence.reason}</dd>
          </div>
          {result.divergence.expected ? (
            <div className="flex flex-wrap gap-2">
              <dt className="opacity-80">{t('expected')}</dt>
              <dd data-sarana-datum="" className="break-all font-mono">
                {result.divergence.expected}
              </dd>
            </div>
          ) : null}
          {result.divergence.found ? (
            <div className="flex flex-wrap gap-2">
              <dt className="opacity-80">{t('found')}</dt>
              <dd data-sarana-datum="" className="break-all font-mono">
                {result.divergence.found}
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </section>
  );
}
