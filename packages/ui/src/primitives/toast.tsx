/**
 * Toast.
 *
 * Two tones and a hard rule: nothing that a person must act on goes in a toast. A toast
 * dismisses itself, cannot be recovered, and is missed by anyone who looked away - so a
 * pending gate, a failed dispatch or an approval request is a banner or a queue item,
 * never this. What belongs here is confirmation of something the user just did.
 *
 * `error` toasts do not auto-dismiss. A message that says something failed and then
 * removes itself before it is read is worse than no message.
 */

import * as ToastPrimitive from '@radix-ui/react-toast';
import {
  forwardRef,
  type ComponentPropsWithoutRef,
  type ElementRef,
  type ReactNode,
} from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';

export const ToastProvider = ToastPrimitive.Provider;

export const ToastViewport = forwardRef<
  ElementRef<typeof ToastPrimitive.Viewport>,
  ComponentPropsWithoutRef<typeof ToastPrimitive.Viewport>
>(function ToastViewport({ className, ...rest }, ref) {
  return (
    <ToastPrimitive.Viewport
      ref={ref}
      className={cn(
        'fixed bottom-0 right-0 z-[var(--z-toast)] flex w-[min(24rem,100vw)]',
        'flex-col gap-2 p-4 outline-none',
        className,
      )}
      {...rest}
    />
  );
});

export type ToastTone = 'neutral' | 'success' | 'error';

const TONES: Record<ToastTone, string> = {
  neutral: 'border-[var(--divider)]',
  success: 'border-[var(--verified)]',
  // Borrowed from the ramp because a failed dispatch genuinely is a hazard-adjacent
  // event, and because an error toast is always accompanied by its own text.
  error: 'border-[var(--sev-3-border)]',
};

export interface ToastProps
  // `title` names the Radix sub-element, not the HTML attribute.
  extends Omit<ComponentPropsWithoutRef<typeof ToastPrimitive.Root>, 'title'> {
  readonly title: ReactNode;
  readonly description?: ReactNode;
  readonly tone?: ToastTone;
  readonly action?: ReactNode;
  /**
   * Accessible name for the close button, in the active locale.
   *
   * Required rather than defaulted to "Close": a default would be an English string
   * shipped to a Tamil-speaking user, and it would be invisible in review because the
   * button renders as an icon. The apps pass `t('common.dismiss')`.
   */
  readonly closeLabel: string;
  /** What the action does, for a screen reader. Radix requires it; so does the user. */
  readonly actionLabel?: string;
}

export const Toast = forwardRef<ElementRef<typeof ToastPrimitive.Root>, ToastProps>(
  function Toast(
    { title, description, tone = 'neutral', action, closeLabel, actionLabel, className, ...rest },
    ref,
  ) {
    return (
      <ToastPrimitive.Root
        ref={ref}
        // An error stays until it is dismissed. Everything else clears itself.
        duration={tone === 'error' ? Number.POSITIVE_INFINITY : 6000}
        className={cn(
          'flex items-start gap-3 rounded-[var(--radius-default)] border-l-4 border',
          'bg-[var(--surface-raised)] p-4 shadow-[var(--shadow-overlay)]',
          TONES[tone],
          className,
        )}
        {...rest}
      >
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <ToastPrimitive.Title className="text-sm font-medium text-[var(--text-primary)]">
            {title}
          </ToastPrimitive.Title>
          {description ? (
            <ToastPrimitive.Description className="text-xs text-[var(--text-muted)]">
              {description}
            </ToastPrimitive.Description>
          ) : null}
        </div>
        {action ? (
          <ToastPrimitive.Action altText={actionLabel ?? closeLabel}>{action}</ToastPrimitive.Action>
        ) : null}
        <ToastPrimitive.Close
          aria-label={closeLabel}
          className={cn(
            'shrink-0 rounded-[var(--radius-cell)] p-1 text-[var(--text-muted)]',
            'hover:text-[var(--text-primary)]',
            FOCUS_RING,
          )}
        >
          <svg viewBox="0 0 12 12" className="size-3" aria-hidden="true">
            <path
              d="m3 3 6 6M9 3l-6 6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </ToastPrimitive.Close>
      </ToastPrimitive.Root>
    );
  },
);
