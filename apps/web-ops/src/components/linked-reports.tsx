'use client';

/**
 * The reports behind an incident, and the cluster dedup put it in.
 *
 * Both halves of the context pane the brief asks for: "linked reports with
 * original-language text and audio playback, transcription confidence, dedup links with
 * similarity". Neither could be built until `GET /incidents/{id}` joined the reports - its
 * docstring had promised them since it was written and its SQL joined none.
 *
 * Four rules run through this component.
 *
 * **The original language leads; the English is secondary.** A dispatcher reading only the
 * translation of a Tamil report is reading a machine's guess at what a frightened person
 * said. `lang` is set on the original so it renders in the right face and a screen reader
 * uses the right voice - a Tamil sentence announced by an English voice is not readable
 * aloud, which for the one person who needs it read aloud makes the report unusable.
 *
 * **Confidence is shown with what follows from it, never as a bare number.** Below the
 * review threshold the report is held for a human, and the row says so. A figure with no
 * consequence attached is one an operator learns to scroll past.
 *
 * **Audio is not played, and the screen says why.** `raw_audio_uri` is an object key.
 * Media signing is not wired (file 08), so an `<audio>` element pointed at it would fail
 * silently - and an operator who presses play and hears nothing concludes the recording is
 * empty rather than that it is unreachable. When the key is already an http(s) URL it is
 * offered as a link instead, so wiring the store lights this up with no change here.
 *
 * **A dedup link is a claim about two reports, and it carries its similarity.** "Merged"
 * with no number behind it is not reviewable. A wrong merge hides a second emergency
 * behind the first: one team is sent and the other household waits for somebody who is not
 * coming, so the evidence for the merge is on screen next to the link.
 */

import {
  Badge,
  ConfidenceMeter,
  EmptyState,
  ReferenceCode,
  RelativeTime,
  SeverityPill,
  Skeleton,
  cn,
} from '@sarana/ui';
import type { ConfidenceBand, SeverityLevel } from '@sarana/ui';
import { useTranslations } from 'next-intl';

import { Link } from '../i18n/routing';
import type { ClusterSibling, LinkedReport } from '../lib/schemas';

/** Below this a transcription is held for a person rather than acted on. */
const REVIEW_THRESHOLD = 0.7;

/** BCP-47 tags, so each original renders in the right face and voice. */
const LANG_TAGS: Record<string, string> = { si: 'si-LK', ta: 'ta-LK', en: 'en-LK' };

function bandFor(confidence: number): ConfidenceBand {
  if (confidence >= 0.85) return 'high';
  if (confidence >= REVIEW_THRESHOLD) return 'medium';
  return 'low';
}

/**
 * Whether this key can actually be fetched by a browser.
 *
 * Object keys look like `reports/2025/11/28/<uuid>.ogg` and are not URLs. Treating one as
 * a URL produces a request to a path on the console's own origin, which 404s - a failure
 * that looks like a missing recording rather than an unwired object store.
 */
export function isPlayable(uri: string | null): boolean {
  return uri !== null && /^https?:\/\//i.test(uri);
}

export interface LinkedReportsProps {
  readonly reports: readonly LinkedReport[];
  readonly loading?: boolean;
  /** Set when the incident read failed. Distinct from "no reports": see below. */
  readonly failed?: boolean;
  readonly className?: string;
}

export function LinkedReports({ reports, loading, failed, className }: LinkedReportsProps) {
  const t = useTranslations('cop');

  if (loading) return <Skeleton className="h-24" />;

  // A failed read is not an empty list. Rendering nothing would say this incident was
  // reported by nobody, which is a statement about the incident rather than about us.
  if (failed) return <p className="text-xs text-[var(--sev-2-fg)]">{t('reportsUnavailable')}</p>;

  if (reports.length === 0) {
    return <p className="text-xs text-[var(--text-muted)]">{t('reportsEmpty')}</p>;
  }

  return (
    <ul className={cn('flex flex-col gap-3', className)}>
      {reports.map((report) => (
        <li
          key={report.report_id}
          data-report-channel={report.channel}
          className="flex flex-col gap-2 rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-3"
        >
          <div className="flex flex-wrap items-center gap-2 text-2xs">
            <Badge tone="neutral">{report.channel}</Badge>
            <RelativeTime value={report.received_at} />
            {report.location_source ? (
              <span className="text-[var(--text-muted)]">
                {t('locationSource')}: {report.location_source}
                {report.location_accuracy_m !== null ? ` ±${report.location_accuracy_m}m` : null}
              </span>
            ) : null}
            {/* How dedup found this report, or that a person did. A link with no evidence
                behind it is a link nobody can review. */}
            {report.similarity !== null ? (
              <span className="text-[var(--text-muted)]">
                {t('similarity')}:{' '}
                <span data-sarana-datum="" className="font-mono">
                  {report.similarity.toFixed(3)}
                </span>
              </span>
            ) : (
              <Badge tone="verified">{t('linkedByHuman')}</Badge>
            )}
          </div>

          {/* The original first and largest. `lang` set so the right face and the right
              voice are used - a Tamil sentence read aloud by an English voice is not
              read aloud at all. */}
          {report.text_original ?? report.raw_text ? (
            <p
              lang={LANG_TAGS[report.detected_language ?? report.reported_language ?? ''] ?? undefined}
              className="text-sm leading-relaxed"
            >
              {report.text_original ?? report.raw_text}
            </p>
          ) : null}

          {report.text_en && report.text_en !== report.text_original ? (
            <p lang="en-LK" className="text-xs text-[var(--text-muted)]">
              {t('translation')}: {report.text_en}
            </p>
          ) : null}

          {report.confidence !== null ? (
            <ConfidenceMeter
              value={report.confidence}
              band={bandFor(report.confidence)}
              bandLabel={t('transcriptionConfidence')}
              // The consequence, not the number alone.
              consequence={
                report.confidence < REVIEW_THRESHOLD
                  ? t('heldForReview')
                  : t('transcriptionAccepted')
              }
            />
          ) : null}

          {report.needs_human_review && report.reviewed_at === null ? (
            <Badge tone="pending">{t('awaitingReview')}</Badge>
          ) : null}

          {report.raw_audio_uri ? (
            isPlayable(report.raw_audio_uri) ? (
              // No caption track, deliberately. The transcript above *is* the caption:
              // the same content, in the same language, already on screen and already
              // carrying its confidence. A WebVTT track generated from it would be a
              // second copy of the transcription that can disagree with the first.
              <audio controls preload="none" src={report.raw_audio_uri} className="w-full">
                {t('audioUnsupported')}
              </audio>
            ) : (
              // Named as present and unreachable. An `<audio>` element pointed at an
              // object key fails silently, and silence reads as an empty recording.
              <p className="text-2xs text-[var(--sev-2-fg)]">{t('audioNotPlayable')}</p>
            )
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export interface DedupLinksProps {
  readonly links: readonly ClusterSibling[];
  readonly className?: string;
}

/**
 * The other incidents in this one's dedup cluster.
 *
 * Renders nothing when there are none, which is most incidents: an "0 duplicates" line on
 * every incident in the queue is noise, and noise is what a dispatcher stops reading.
 */
export function DedupLinks({ links, className }: DedupLinksProps) {
  const t = useTranslations('cop');
  if (links.length === 0) return null;

  return (
    <section className={cn('flex flex-col gap-1', className)}>
      <h3 className="text-sm font-medium">{t('dedupLinks')}</h3>
      <p className="text-2xs text-[var(--text-muted)]">{t('dedupHint')}</p>
      <ul className="flex flex-col gap-1">
        {links.map((sibling) => (
          <li key={sibling.id} className="flex flex-wrap items-center gap-2 text-xs">
            <SeverityPill level={sibling.severity as SeverityLevel} locale="en" />
            <Link
              href={`/ops/incidents/${sibling.id}`}
              className="underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
            >
              <ReferenceCode code={sibling.public_ref} />
            </Link>
            <span data-sarana-datum="" className="font-mono text-2xs">
              {sibling.gn_division_code}
            </span>
            {/* Which row the cluster treats as the real incident. A merge that hid the
                primary would leave a dispatcher working the duplicate. */}
            <Badge tone={sibling.is_cluster_primary ? 'verified' : 'neutral'}>
              {sibling.is_cluster_primary ? t('clusterPrimary') : t('clusterDuplicate')}
            </Badge>
            <Badge tone="neutral">{sibling.status}</Badge>
            <RelativeTime value={sibling.first_reported_at} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Shown when an incident has neither reports nor siblings, so the pane is not blank. */
export function NoContext() {
  const t = useTranslations('cop');
  return <EmptyState title={t('reportsEmpty')} description={t('reportsEmptyHint')} />;
}
