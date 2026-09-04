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
  LKRAmount,
  RadioGroup,
  ReferenceCode,
  RelativeTime,
  Textarea,
  cn,
} from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { gatewayFetch } from '../lib/gateway-client';
import { useAnomalies, useLedger } from '../lib/queries';
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
  const ledger = useLedger();

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

      <h2 className="text-sm font-medium">{t('ledger')}</h2>
      <DataTable<LedgerEntry>
        caption={t('ledger')}
        rows={ledger.data ?? []}
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
