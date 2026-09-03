'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * PendingGateBanner.
 *
 * SARANA has exactly two mandatory human gates - committing a life-safety dispatch
 * action, and releasing a financial disbursement - and no flag anywhere bypasses either.
 * This is the component that makes them work in practice, because a gate that nobody
 * notices is a queue, not a gate.
 *
 * It escalates with the age of the *oldest* waiting item, not the newest and not the
 * count. Sorting by count lets one very old item hide behind a quiet afternoon; the
 * question a gate has to answer is "what has been waiting longest", because that is the
 * item whose delay is doing damage.
 *
 * Thresholds: 2 minutes takes it from a line to a prominent panel, 5 minutes makes it
 * persistent and offers sound. Both are deliberately short. During Cyclone Ditwah the
 * window between a division being identified as at risk and needing to be evacuated was
 * measured in minutes, and an approval sitting unseen for five of them is the failure
 * mode this whole surface exists to prevent.
 */

import { useEffect, useState, type ReactNode } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';

export type GateKind = 'dispatch' | 'disbursement';

export type GateUrgency = 'waiting' | 'prominent' | 'persistent';

/** Seconds. Past each of these the banner changes weight. */
export const GATE_PROMINENT_AFTER_SECONDS = 120;
export const GATE_PERSISTENT_AFTER_SECONDS = 300;

export function urgencyFor(waitingSeconds: number): GateUrgency {
  if (waitingSeconds >= GATE_PERSISTENT_AFTER_SECONDS) return 'persistent';
  if (waitingSeconds >= GATE_PROMINENT_AFTER_SECONDS) return 'prominent';
  return 'waiting';
}

const URGENCY_CLASSES: Record<GateUrgency, string> = {
  // All three are --pending. The escalation is in weight and size, never in hue: turning
  // the banner red at five minutes would put a severity colour on a workflow state and
  // break the one rule the palette exists to keep.
  waiting: 'border-[var(--pending)] bg-transparent',
  prominent: 'border-[var(--pending)] bg-[var(--surface-raised)] shadow-[var(--shadow-raised)]',
  persistent:
    'border-[var(--pending)] border-2 bg-[var(--surface-raised)] shadow-[var(--shadow-overlay)]',
};

export interface PendingGateBannerProps {
  readonly kind: GateKind;
  /** How many items are waiting. */
  readonly count: number;
  /** UTC ISO-8601 of the oldest item's `waiting_since`. Drives the escalation. */
  readonly oldestWaitingSince: string;
  /** Injectable clock, so a story and a test are deterministic. */
  readonly now?: Date;
  /** e.g. "2 dispatches awaiting approval". The caller formats the count in. */
  readonly title: (count: number) => string;
  /** e.g. "Oldest has been waiting 6 minutes". The caller formats the duration in. */
  readonly ageLabel: (seconds: number) => string;
  readonly action: ReactNode;
  /** Offered only once the wait is persistent. Omit to leave sound unavailable. */
  readonly onEnableSound?: () => void;
  readonly soundLabel?: string;
  readonly className?: string;
}

export function PendingGateBanner({
  kind,
  count,
  oldestWaitingSince,
  now,
  title,
  ageLabel,
  action,
  onEnableSound,
  soundLabel,
  className,
}: PendingGateBannerProps) {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (now) return;
    // Re-render every 15 seconds so the banner escalates on its own. An operator who
    // walked away has to come back to a banner that has grown, not to a stale one that
    // still says "waiting 20 seconds" ten minutes later.
    const timer = setInterval(() => setTick((value) => value + 1), 15_000);
    return () => clearInterval(timer);
  }, [now]);

  // `tick` is read so the effect's re-render is not optimised away by a linter.
  void tick;

  const reference = now ?? new Date();
  const waitingSeconds = Math.max(
    0,
    Math.round((reference.getTime() - new Date(oldestWaitingSince).getTime()) / 1000),
  );
  const urgency = urgencyFor(waitingSeconds);

  if (count === 0) return null;

  return (
    <div
      data-gate-kind={kind}
      data-gate-urgency={urgency}
      // `alert` once it is persistent, `status` before that. A gate that has been waiting
      // five minutes should interrupt; one that arrived ten seconds ago should not
      // interrupt whatever the operator is reading.
      role={urgency === 'persistent' ? 'alert' : 'status'}
      aria-live={urgency === 'persistent' ? 'assertive' : 'polite'}
      className={cn(
        'flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--radius-default)] border',
        'px-4 py-3 text-[var(--pending)]',
        URGENCY_CLASSES[urgency],
        className,
      )}
    >
      <GateMark urgency={urgency} />

      <div className="flex min-w-0 flex-1 flex-col">
        <span
          className={cn(
            'text-sm',
            urgency === 'waiting' ? 'font-medium' : 'font-semibold',
          )}
        >
          {title(count)}
        </span>
        <span data-sarana-datum="" className="font-mono text-2xs opacity-90">
          {ageLabel(waitingSeconds)}
        </span>
      </div>

      <div className="flex items-center gap-2">
        {urgency === 'persistent' && onEnableSound && soundLabel ? (
          <button
            type="button"
            onClick={onEnableSound}
            className={cn(
              'min-h-[var(--touch-target-min)] rounded-[var(--radius-default)] px-3',
              'text-xs underline',
              FOCUS_RING,
            )}
          >
            {soundLabel}
          </button>
        ) : null}
        {action}
      </div>
    </div>
  );
}

/** Shape escalates with the wait, so the state is not carried by size alone. */
function GateMark({ urgency }: { readonly urgency: GateUrgency }) {
  return (
    <svg viewBox="0 0 16 16" className="size-4 shrink-0" aria-hidden="true">
      <circle
        cx="8"
        cy="8"
        r="6.5"
        fill="none"
        stroke="currentColor"
        strokeWidth={urgency === 'waiting' ? 1.5 : 2}
      />
      {/* A clock hand at 12, then progressively further round: the mark itself says
          how long this has been sitting there. */}
      <path
        d={
          urgency === 'waiting'
            ? 'M8 4.5V8'
            : urgency === 'prominent'
              ? 'M8 4.5V8l2.5 1.5'
              : 'M8 4.5V8l3 2.5'
        }
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
