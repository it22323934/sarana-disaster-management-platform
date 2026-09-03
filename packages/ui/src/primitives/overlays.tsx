/**
 * Dialog, Sheet, Popover and Tooltip.
 *
 * Grouped because they share one rule that is easy to get wrong separately: a Tooltip
 * may never be the only place information appears. Tooltips do not open on touch, do not
 * survive a screenshot, and are missed entirely by anyone reading with a magnifier. On a
 * platform read on handsets in the field, a tooltip is an enhancement and never a
 * carrier - so every use of `Tooltip` in the apps pairs it with visible text, and the
 * components that would be tempted to cheat (`HashDisplay`, `ConfidenceMeter`) render
 * their full meaning inline instead.
 *
 * Dialog and Sheet are the same primitive with different geometry: Dialog centres for a
 * decision, Sheet slides from the edge for a task that needs the context behind it to
 * stay visible - which is why the two gate surfaces are Dialogs, not Sheets. A gate
 * should not let you keep working behind it.
 */

import * as DialogPrimitive from '@radix-ui/react-dialog';
import * as PopoverPrimitive from '@radix-ui/react-popover';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import {
  forwardRef,
  type ComponentPropsWithoutRef,
  type ElementRef,
  type ReactNode,
} from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';

const OVERLAY =
  'fixed inset-0 z-[var(--z-overlay)] bg-black/60 ' +
  'data-[state=open]:animate-in data-[state=closed]:animate-out';

const PANEL =
  'z-[var(--z-dialog)] border border-[var(--divider)] bg-[var(--surface-raised)] ' +
  'shadow-[var(--shadow-overlay)] text-[var(--text-primary)]';

export const DialogRoot = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export interface DialogContentProps
  // `title` and `description` are omitted from the DOM props: here they name the two
  // Radix sub-elements, not the HTML `title` attribute (which would render a tooltip).
  extends Omit<ComponentPropsWithoutRef<typeof DialogPrimitive.Content>, 'title'> {
  /** Required. A dialog with no accessible name is announced as "dialog" and nothing else. */
  readonly title: ReactNode;
  readonly description?: ReactNode;
}

export const DialogContent = forwardRef<
  ElementRef<typeof DialogPrimitive.Content>,
  DialogContentProps
>(function DialogContent({ title, description, className, children, ...rest }, ref) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className={OVERLAY} />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(
          PANEL,
          'fixed left-1/2 top-1/2 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2',
          '-translate-y-1/2 rounded-[var(--radius-surface)] p-6',
          'max-h-[calc(100vh-4rem)] overflow-y-auto',
          className,
        )}
        {...rest}
      >
        <DialogPrimitive.Title className="text-lg font-semibold">{title}</DialogPrimitive.Title>
        {description ? (
          <DialogPrimitive.Description className="mt-1 text-sm text-[var(--text-muted)]">
            {description}
          </DialogPrimitive.Description>
        ) : null}
        <div className="mt-4">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
});

export const SheetRoot = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

export type SheetSide = 'right' | 'left' | 'bottom';

const SHEET_SIDES: Record<SheetSide, string> = {
  right: 'inset-y-0 right-0 h-full w-[min(28rem,100vw)] border-l',
  left: 'inset-y-0 left-0 h-full w-[min(28rem,100vw)] border-r',
  // Bottom is the mobile default: a right-hand sheet on a 360px handset is a full-screen
  // panel that animates in from an edge nobody can see.
  bottom: 'inset-x-0 bottom-0 max-h-[85vh] w-full rounded-t-[var(--radius-surface)] border-t',
};

export interface SheetContentProps
  extends Omit<ComponentPropsWithoutRef<typeof DialogPrimitive.Content>, 'title'> {
  readonly title: ReactNode;
  readonly description?: ReactNode;
  readonly side?: SheetSide;
}

export const SheetContent = forwardRef<
  ElementRef<typeof DialogPrimitive.Content>,
  SheetContentProps
>(function SheetContent(
  { title, description, side = 'right', className, children, ...rest },
  ref,
) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className={OVERLAY} />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(PANEL, 'fixed overflow-y-auto p-6', SHEET_SIDES[side], className)}
        {...rest}
      >
        <DialogPrimitive.Title className="text-lg font-semibold">{title}</DialogPrimitive.Title>
        {description ? (
          <DialogPrimitive.Description className="mt-1 text-sm text-[var(--text-muted)]">
            {description}
          </DialogPrimitive.Description>
        ) : null}
        <div className="mt-4">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
});

export const PopoverRoot = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverAnchor = PopoverPrimitive.Anchor;

export const PopoverContent = forwardRef<
  ElementRef<typeof PopoverPrimitive.Content>,
  ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(function PopoverContent({ className, align = 'start', sideOffset = 6, ...rest }, ref) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        ref={ref}
        align={align}
        sideOffset={sideOffset}
        className={cn(
          PANEL,
          'w-[min(22rem,calc(100vw-2rem))] rounded-[var(--radius-default)] p-4 outline-none',
          FOCUS_RING,
          className,
        )}
        {...rest}
      />
    </PopoverPrimitive.Portal>
  );
});

/**
 * Wrap the app once. `delayDuration` is 300ms rather than the 700ms default: an operator
 * scanning a dense table should not have to hold still for most of a second.
 */
export function TooltipProvider({ children }: { readonly children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delayDuration={300} skipDelayDuration={200}>
      {children}
    </TooltipPrimitive.Provider>
  );
}

export interface TooltipProps {
  /**
   * Supplementary only. If the tooltip is the only place this appears, it is missing
   * from the interface - see the file docstring.
   */
  readonly content: ReactNode;
  readonly children: ReactNode;
  readonly side?: 'top' | 'right' | 'bottom' | 'left';
}

export function Tooltip({ content, children, side = 'top' }: TooltipProps) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className={cn(
            PANEL,
            'max-w-[18rem] rounded-[var(--radius-default)] px-3 py-2 text-xs',
            'z-[var(--z-toast)]',
          )}
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
