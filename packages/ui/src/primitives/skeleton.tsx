/**
 * Skeleton.
 *
 * A static block, not a shimmer. Motion in this product means "something changed that
 * you need to notice"; an animated placeholder spends that signal on the fact that a
 * request is in flight, which is the least important thing on the screen.
 *
 * It is `aria-hidden` and paired with a live region by the caller, so a screen reader
 * hears "loading incidents" once instead of counting eleven grey rectangles.
 */

import type { HTMLAttributes } from 'react';

import { cn } from '../lib/cn.js';

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** Rendered as a text line: height follows the type scale rather than a fixed px. */
  readonly line?: boolean;
}

export function Skeleton({ line = false, className, ...rest }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      data-sarana-skeleton=""
      className={cn(
        'bg-[var(--surface-raised)] rounded-[var(--radius-cell)]',
        line ? 'h-[1em] w-full' : 'h-full w-full',
        className,
      )}
      {...rest}
    />
  );
}
