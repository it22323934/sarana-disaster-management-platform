'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * Button.
 *
 * Five variants and no sixth. `danger` is the interesting one: it is the only control in
 * the library allowed to borrow a severity colour, and it does so because the actions it
 * marks - cancelling a live alert, reversing a disbursement - *are* hazard-level actions.
 * It is deliberately not available as a general "destructive" style for deleting a draft.
 */

import { Slot } from '@radix-ui/react-slot';
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cn } from '../lib/cn.js';
import { DISABLED, FOCUS_RING } from '../lib/focus.js';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'link';
export type ButtonSize = 'sm' | 'md' | 'lg';

const VARIANTS: Record<ButtonVariant, string> = {
  // Darkens on hover. The brief's --signal-400 would drop the white label to 3.16:1.
  primary:
    'bg-[var(--signal-500)] text-[var(--on-signal)] hover:bg-[var(--signal-600)] ' +
    'border border-transparent',
  secondary:
    'bg-transparent text-[var(--text-primary)] border border-[var(--divider)] ' +
    'hover:bg-[var(--surface-raised)]',
  ghost:
    'bg-transparent text-[var(--text-primary)] border border-transparent ' +
    'hover:bg-[var(--surface-raised)]',
  // The only borrowed severity colour in the library. See the file docstring.
  danger:
    'bg-[var(--sev-3)] text-[var(--on-fill)] hover:bg-[var(--sev-4)] border border-transparent',
  link:
    'bg-transparent text-[var(--text-accent)] underline underline-offset-2 border-0 ' +
    'px-0 h-auto min-h-0 hover:no-underline',
};

const SIZES: Record<ButtonSize, string> = {
  // 32px tall. Only legal inside a data-dense row, where the row itself is the target.
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-11 px-4 text-sm gap-2',
  lg: 'h-12 px-5 text-base gap-2',
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant?: ButtonVariant;
  readonly size?: ButtonSize;
  /** Render as the child element, keeping the styling. For wrapping a router link. */
  readonly asChild?: boolean;
  /**
   * Shown instead of the label while an action is in flight.
   *
   * A busy button stays in the accessibility tree with `aria-busy` rather than being
   * replaced by a spinner: a screen reader user who cannot see the spinner still needs
   * to know which control they are on.
   */
  readonly busy?: boolean;
  readonly busyLabel?: string;
  readonly children?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    asChild = false,
    busy = false,
    busyLabel,
    className,
    children,
    disabled,
    type,
    ...rest
  },
  ref,
) {
  const Component = asChild ? Slot : 'button';

  return (
    <Component
      ref={ref}
      // An unset `type` inside a form defaults to `submit`, which has fired more
      // accidental submissions than any other HTML default.
      type={asChild ? undefined : (type ?? 'button')}
      aria-busy={busy || undefined}
      disabled={disabled ?? busy}
      className={cn(
        'inline-flex items-center justify-center rounded-[var(--radius-default)]',
        'font-medium transition-colors duration-[var(--motion-state)]',
        FOCUS_RING,
        DISABLED,
        SIZES[size],
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {busy && busyLabel ? busyLabel : children}
    </Component>
  );
});
