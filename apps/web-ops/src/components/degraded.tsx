'use client';

/**
 * Degraded states, designed rather than discovered.
 *
 * The rule these all serve: **never render a rule-based rank as if it were the model's.**
 * The console shows agent output on several screens and the agents are not wired to the
 * live stack, so the difference between "the agent ranked this" and "nothing ranked this,
 * here is the deterministic order" has to be visible on the screen, every time, in the
 * operator's language.
 *
 * These are banners rather than toasts on purpose. A toast dismisses itself and is missed
 * by anyone who looked away; a degraded platform is a standing condition, not an event.
 */

import { useTranslations } from 'next-intl';
import type { ReactNode } from 'react';

import { cn } from '@sarana/ui';

export type DegradedKind = 'agent' | 'backend' | 'reasoning';

export interface DegradedBannerProps {
  readonly kind: DegradedKind;
  /** For `backend`: how old the cached picture is, already formatted and localised. */
  readonly age?: string;
  readonly className?: string;
}

export function DegradedBanner({ kind, age, className }: DegradedBannerProps) {
  const t = useTranslations('degraded');

  const copy: Record<DegradedKind, { title: string; body: string }> = {
    agent: { title: t('agentUnavailable'), body: t('agentExplanation') },
    backend: {
      title: t('backendUnreachable'),
      body: t('backendExplanation', { age: age ?? '' }),
    },
    reasoning: { title: t('reasoningUnavailable'), body: t('reasoningExplanation') },
  };

  return (
    <div
      role="status"
      data-degraded={kind}
      className={cn(
        'flex items-start gap-3 rounded-[var(--radius-default)] border px-4 py-3',
        // The watch band, not the warning band. A degraded service is a condition the
        // operator must work around; it is not itself a hazard, and painting it red would
        // put it in the same visual register as a class-3 warning.
        'border-[var(--sev-2-border)] bg-[var(--sev-2-bg)] text-[var(--sev-2-fg)]',
        className,
      )}
    >
      <svg viewBox="0 0 12 12" className="mt-0.5 size-3.5 shrink-0" aria-hidden="true">
        <path d="M6 1.5 11 10.5H1Z" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path
          d="M6 5v2.2M6 8.6v.3"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </svg>
      <div className="flex flex-col gap-0.5">
        <p className="text-sm font-medium">{copy[kind].title}</p>
        <p className="text-xs opacity-90">{copy[kind].body}</p>
      </div>
    </div>
  );
}

export interface ErrorPanelProps {
  readonly error: unknown;
  readonly children?: ReactNode;
  readonly className?: string;
}

/**
 * A failure the user can act on.
 *
 * The correlation ID is shown, not hidden behind a details toggle. It is the only thing
 * that connects what the operator saw to what the server logged, and asking someone to
 * find it during an incident is asking them not to report the problem.
 */
export function ErrorPanel({ error, children, className }: ErrorPanelProps) {
  const t = useTranslations('errors');
  const problem =
    typeof error === 'object' && error !== null && 'problem' in error
      ? (error as { problem: { detail?: string | null; title: string; correlation_id: string } })
          .problem
      : null;

  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col gap-2 rounded-[var(--radius-default)] border px-4 py-3',
        'border-[var(--sev-3-border)] bg-[var(--sev-3-bg)] text-[var(--sev-3-fg)]',
        className,
      )}
    >
      <p className="text-sm font-medium">{problem?.title ?? t('title')}</p>
      <p className="text-xs opacity-90">{problem?.detail ?? t('generic')}</p>
      {problem?.correlation_id ? (
        <p className="text-2xs opacity-80">
          {t('correlationId')}:{' '}
          <span data-sarana-datum="" className="font-mono">
            {problem.correlation_id}
          </span>
        </p>
      ) : null}
      {children}
    </div>
  );
}
