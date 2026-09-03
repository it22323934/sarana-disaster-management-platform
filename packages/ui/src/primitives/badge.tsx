/**
 * Badge. A neutral status pill.
 *
 * It has no severity tone on purpose. Anything that carries a hazard level uses
 * `SeverityPill`, which cannot be rendered without a shape and a label; a Badge with a
 * `tone="danger"` prop would be the obvious way to bypass that rule, so it does not
 * exist.
 */

import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '../lib/cn.js';

export type BadgeTone = 'neutral' | 'accent' | 'verified' | 'pending';

const TONES: Record<BadgeTone, string> = {
  neutral: 'bg-[var(--surface-raised)] text-[var(--text-muted)] border-[var(--divider)]',
  accent: 'bg-transparent text-[var(--text-accent)] border-[var(--text-accent)]',
  verified: 'bg-transparent text-[var(--verified)] border-[var(--verified)]',
  // The "a human must act" colour. Spend it nowhere else - see palette.ts.
  pending: 'bg-transparent text-[var(--pending)] border-[var(--pending)]',
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  readonly tone?: BadgeTone;
  readonly children: ReactNode;
}

export function Badge({ tone = 'neutral', className, children, ...rest }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5',
        'text-2xs font-medium leading-none',
        TONES[tone],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
