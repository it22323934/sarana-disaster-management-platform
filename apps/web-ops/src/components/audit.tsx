'use client';

/**
 * The auditor's view: the ledger, and the anomaly flags with their disposition workflow.
 *
 * Two rules run through this screen, both from ADR-009 and both non-negotiable:
 *
 * **A flag is a pattern, not a finding, and it names nobody.** Every flag renders its
 * `innocent_explanations` — the ordinary reasons this pattern occurs — *above* anything
 * that could read as suspicion, and `what_would_resolve_it` beside them. A flag shown
 * alone is an accusation, and this platform does not accuse people.
 *
 * **A disposition requires a note, including for a false positive.** `FALSE_POSITIVE` is
 * a first-class outcome, not a failure to be hidden: the published false-positive rate is
 * only meaningful if somebody can read why each one was called. `ledger-svc` enforces the
 * note; the console makes the button unreachable without one so the refusal never happens.
 *
 * The reader is also told that their own reads are audited. An auditor who discovers that
 * later has been surprised by their own tooling.
 */

import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  HashDisplay,
  Input,
  LKRAmount,
  RadioGroup,
  ReferenceCode,
  RelativeTime,
  Select,
  Textarea,
  cn,
} from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { gatewayFetch } from '../lib/gateway-client';
import { useAnchors, useAnomalies, useLedger } from '../lib/queries';
import { ledgerFilename, ledgerToCsv } from './ledger-export';
import {
  ANOMALY_DISPOSITIONS,
  flagContext,
  isOpenAnomaly,
  type Anomaly,
  type AnomalyDisposition,
  type LedgerEntry,
} from '../lib/schemas';
import { ErrorPanel } from './degraded';

export function AuditLedger() {
  const t = useTranslations('audit');
  const common = useTranslations('common');
  const [fromSeq, setFromSeq] = useState(0);
  const [typeFilter, setTypeFilter] = useState('');
  const ledger = useLedger(fromSeq);

  /**
   * Filtered in the browser, on purpose, and only by entry type.
   *
   * `GET /ledger` pages from a sequence number and the console asks for 200 rows at a
   * time, so this narrows what is already on screen rather than pretending to search the
   * whole chain. The distinction is on the page: an auditor who believes a client-side
   * filter searched four million entries has drawn a conclusion from a page.
   */
  const rows = useMemo(() => {
    const all = ledger.data ?? [];
    return typeFilter ? all.filter((entry) => entry.entry_type === typeFilter) : all;
  }, [ledger.data, typeFilter]);

  const entryTypes = useMemo(
    () => [...new Set((ledger.data ?? []).map((entry) => entry.entry_type ?? ''))]
      .filter((value) => value.length > 0)
      .sort(),
    [ledger.data],
  );

  if (ledger.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={ledger.error} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">{t('title')}</h1>
        {/* Said up front, not discovered later. */}
        <p className="text-2xs text-[var(--text-muted)]">{t('readsAreAudited')}</p>
      </header>

      <Anchors />

      <h2 className="text-sm font-medium">{t('ledger')}</h2>

      <div className="flex flex-wrap items-end gap-4">
        <Input
          label={t('fromSeq')}
          description={t('fromSeqHint')}
          datum
          inputMode="numeric"
          value={String(fromSeq)}
          onChange={(event) => setFromSeq(Number(event.target.value.replace(/\D/g, '')) || 0)}
        />
        <Select
          label={t('entryType')}
          placeholder={t('allTypes')}
          value={typeFilter}
          onValueChange={setTypeFilter}
          options={entryTypes.map((value) => ({ value, label: value }))}
        />
        <ExportButton rows={rows} />
      </div>

      {/* What this page is and is not. A count with no statement of its window invites
          the conclusion that it is the whole ledger. */}
      <p className="text-2xs text-[var(--text-muted)]">
        {t('pageWindow', { shown: rows.length, from: fromSeq })}
      </p>
      <DataTable<LedgerEntry>
        caption={t('ledger')}
        rows={rows}
        rowKey={(entry) => entry.id}
        height="calc(100vh - 20rem)"
        empty={<EmptyState title={t('ledgerEmpty')} description={t('ledgerEmptyHint')} />}
        columns={[
          {
            key: 'seq',
            header: t('seq'),
            width: '6rem',
            numeric: true,
            cell: (entry) => (
              <span data-sarana-datum="" className="font-mono">
                {entry.seq}
              </span>
            ),
          },
          {
            key: 'type',
            header: t('entryType'),
            width: '12rem',
            cell: (entry) => <Badge tone="neutral">{entry.entry_type ?? '—'}</Badge>,
          },
          {
            key: 'amount',
            header: t('amount'),
            width: '12rem',
            numeric: true,
            cell: (entry) =>
              entry.amount_lkr_cents === null ? '—' : <LKRAmount cents={entry.amount_lkr_cents} />,
          },
          {
            key: 'hash',
            header: t('hash'),
            cell: (entry) => (
              <HashDisplay
                hash={entry.entry_hash}
                truncateTo={12}
                copyLabel={common('copy')}
                copiedLabel={common('copied')}
              />
            ),
          },
          {
            key: 'anchor',
            header: t('anchorDate'),
            width: '10rem',
            cell: (entry) =>
              entry.anchor_date ? (
                <span data-sarana-datum="" className="font-mono text-xs">
                  {entry.anchor_date}
                </span>
              ) : (
                '—'
              ),
          },
        ]}
      />
    </div>
  );
}

export function AnomalyReview() {
  const t = useTranslations('audit');
  const anomalies = useAnomalies();

  if (anomalies.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={anomalies.error} />
      </div>
    );
  }

  const open = (anomalies.data ?? []).filter(isOpenAnomaly);

  return (
    <div className="flex flex-col gap-4 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">{t('anomalies')}</h1>
        <p className="text-xs text-[var(--text-muted)]">{t('neverNames')}</p>
        <p className="text-2xs text-[var(--text-muted)]">{t('readsAreAudited')}</p>
      </header>

      {open.length === 0 ? (
        <EmptyState title={t('anomaliesEmpty')} description={t('anomaliesEmptyHint')} />
      ) : (
        <ul className="flex flex-col gap-4">
          {open.map((anomaly) => (
            <li key={anomaly.id}>
              <FlagCard anomaly={anomaly} onDisposed={() => void anomalies.refetch()} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FlagCard({
  anomaly,
  onDisposed,
}: {
  readonly anomaly: Anomaly;
  readonly onDisposed: () => void;
}) {
  const t = useTranslations('audit');
  const dispositions = useTranslations('disposition');

  const [disposition, setDisposition] = useState<AnomalyDisposition>('REVIEWED_NO_ACTION');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);

  const context = flagContext(anomaly);

  async function dispose(): Promise<void> {
    setBusy(true);
    setFailure(null);
    try {
      await gatewayFetch(`anomalies/${anomaly.id}/dispose`, {
        method: 'POST',
        body: { disposition, note: note.trim() },
        idempotencyKey: `dispose-${anomaly.id}`,
      });
      onDisposed();
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      className={cn(
        'flex flex-col gap-3 rounded-[var(--radius-default)] border',
        'border-[var(--divider)] bg-[var(--surface-card)] p-4',
      )}
    >
      <header className="flex flex-wrap items-baseline gap-3">
        <ReferenceCode code={anomaly.detector} kind={t('detector')} />
        <span className="text-2xs text-[var(--text-muted)]">
          {t('score')}:{' '}
          <span data-sarana-datum="" className="font-mono">
            {anomaly.score.toFixed(2)}
          </span>
        </span>
        <span className="ml-auto">
          <RelativeTime value={anomaly.raised_at} />
        </span>
      </header>

      {context.pattern_summary ? (
        <p className="text-sm">{context.pattern_summary}</p>
      ) : null}

      {/* The ordinary reasons first. A flag read without them is read as an accusation. */}
      {context.innocent_explanations.length > 0 ? (
        <section>
          <h3 className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {t('innocentExplanations')}
          </h3>
          <ul className="ml-4 list-disc text-xs">
            {context.innocent_explanations.map((explanation) => (
              <li key={explanation}>{explanation}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {context.what_would_resolve_it.length > 0 ? (
        <section>
          <h3 className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {t('whatWouldResolve')}
          </h3>
          <ul className="ml-4 list-disc text-xs">
            {context.what_would_resolve_it.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {failure ? <ErrorPanel error={failure} /> : null}

      <div className="flex flex-col gap-3 border-t border-[var(--divider)] pt-3">
        <RadioGroup
          legend={t('disposition')}
          value={disposition}
          onValueChange={(value) => setDisposition(value as AnomalyDisposition)}
          options={ANOMALY_DISPOSITIONS.map((value) => ({
            value,
            label: dispositions(value),
          }))}
        />
        <Textarea
          label={t('disposeNote')}
          description={t('disposeNoteHint')}
          required
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        <Button
          variant="primary"
          // Unreachable without a note, for every outcome including a false positive.
          // `ledger-svc` refuses a note-less disposition; this stops the refusal happening.
          disabled={note.trim().length === 0 || busy}
          busy={busy}
          busyLabel={t('dispose')}
          onClick={dispose}
          className="self-start"
        >
          {t('dispose')}
        </Button>
      </div>
    </article>
  );
}

/**
 * Download the rows on screen as CSV.
 *
 * A blob and an object URL rather than a server round trip: the rows are already here, and
 * a second fetch would produce a file that can differ from what the auditor was looking at
 * when they pressed the button.
 *
 * The filename carries the seq range, and the button says how many rows it will write.
 * "Export" alone invites the belief that the file is the whole ledger; it is one page of
 * it, and an auditor who reconciles against a page and reports a total is the failure this
 * label exists to stop.
 */
function ExportButton({ rows }: { readonly rows: readonly LedgerEntry[] }) {
  const t = useTranslations('audit');

  function download(): void {
    const blob = new Blob([ledgerToCsv(rows)], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = ledgerFilename(rows);
    anchor.click();
    // Revoked immediately. The click has already started the download, and an object URL
    // left alive holds the whole blob in memory for the life of the document.
    URL.revokeObjectURL(url);
  }

  return (
    <Button variant="secondary" disabled={rows.length === 0} onClick={download}>
      {t('exportCsv', { count: rows.length })}
    </Button>
  );
}

/**
 * The published daily anchors, and the half of the guarantee that is missing.
 *
 * Each day the ledger is Merkle-rooted, chained to the previous day and published. The
 * root is computed and the chain is real; `s3_object_lock_uri` is null until an object
 * store is wired, **and that URI is the entire external half of the guarantee**. Without
 * it the chain is verifiable only against a database the operator controls, which is a
 * much weaker claim than a green tick suggests.
 *
 * So the unanchored days are counted and stated above the table rather than left as a
 * column of dashes somebody has to notice.
 */
function Anchors() {
  const t = useTranslations('audit');
  const common = useTranslations('common');
  const anchors = useAnchors();

  if (anchors.isError) return <ErrorPanel error={anchors.error} />;

  const rows = anchors.data?.anchors ?? [];
  const unanchored = rows.filter((anchor) => anchor.s3_object_lock_uri === null).length;

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium">{t('anchorsTitle')}</h2>

      {unanchored > 0 ? (
        <p
          role="status"
          className="rounded-[var(--radius-default)] border border-[var(--sev-2-border)] bg-[var(--sev-2-bg)] px-3 py-2 text-xs text-[var(--sev-2-fg)]"
        >
          {t('unanchoredDays', { count: unanchored })}
        </p>
      ) : null}

      {/* The verifier CLI, named on the page. An auditor who has to ask how to check this
          independently is an auditor who checks it through us. */}
      <p className="text-2xs text-[var(--text-muted)]">{t('verifyCliHint')}</p>
      <pre
        data-sarana-datum=""
        className="overflow-x-auto rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-2 font-mono text-2xs"
      >
        sarana-verify --from-seq 1 --to-seq {rows.at(-1)?.last_seq ?? 0}
      </pre>

      <DataTable<(typeof rows)[number]>
        caption={t('anchorsTitle')}
        rows={rows}
        rowKey={(anchor) => anchor.date}
        height="16rem"
        empty={<EmptyState title={t('anchorsEmpty')} description={t('anchorsEmptyHint')} />}
        columns={[
          {
            key: 'date',
            header: t('anchorDate'),
            width: '10rem',
            cell: (anchor) => (
              <span data-sarana-datum="" className="font-mono text-xs">
                {anchor.date}
              </span>
            ),
          },
          {
            key: 'range',
            header: t('seq'),
            width: '12rem',
            numeric: true,
            cell: (anchor) => (
              <span data-sarana-datum="" className="font-mono text-xs">
                {anchor.first_seq}–{anchor.last_seq}
              </span>
            ),
          },
          {
            key: 'entries',
            header: t('entryCount'),
            width: '8rem',
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
            width: '16rem',
            // The absence is the finding, so it is a badge rather than a dash.
            cell: (anchor) =>
              anchor.s3_object_lock_uri ? (
                <span data-sarana-datum="" className="font-mono text-2xs">
                  {anchor.s3_object_lock_uri}
                </span>
              ) : (
                <Badge tone="pending">{t('noExternalAnchor')}</Badge>
              ),
          },
        ]}
      />
    </section>
  );
}
