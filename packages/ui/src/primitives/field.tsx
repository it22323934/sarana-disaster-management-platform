/**
 * The label / description / error scaffolding every form control shares.
 *
 * Wiring `aria-describedby` and `aria-invalid` by hand on each control is how a form
 * ends up with an error message that is visible but unannounced. `useFieldIds` generates
 * the ids once and every control in this directory consumes them the same way.
 */

import * as LabelPrimitive from '@radix-ui/react-label';
import { useId, type ReactNode } from 'react';

import { cn } from '../lib/cn.js';

export interface FieldIds {
  readonly controlId: string;
  readonly descriptionId: string | undefined;
  readonly errorId: string | undefined;
  /** The value for the control's `aria-describedby`. Undefined when there is nothing. */
  readonly describedBy: string | undefined;
}

export function useFieldIds(options: {
  hasDescription: boolean;
  hasError: boolean;
  id?: string;
}): FieldIds {
  const generated = useId();
  const controlId = options.id ?? `sarana-${generated}`;
  const descriptionId = options.hasDescription ? `${controlId}-description` : undefined;
  const errorId = options.hasError ? `${controlId}-error` : undefined;
  // Error first: a screen reader reads them in order, and the problem matters more than
  // the hint the reader has already heard once.
  const describedBy = [errorId, descriptionId].filter(Boolean).join(' ') || undefined;
  return { controlId, descriptionId, errorId, describedBy };
}

export interface FieldProps {
  readonly label: ReactNode;
  readonly htmlFor: string;
  readonly description?: ReactNode;
  readonly error?: ReactNode;
  readonly descriptionId?: string;
  readonly errorId?: string;
  readonly required?: boolean;
  readonly className?: string;
  readonly children: ReactNode;
}

export function Field({
  label,
  htmlFor,
  description,
  error,
  descriptionId,
  errorId,
  required = false,
  className,
  children,
}: FieldProps) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <LabelPrimitive.Root
        htmlFor={htmlFor}
        className="text-sm font-medium text-[var(--text-primary)]"
      >
        {label}
        {required ? (
          // The asterisk is decoration; the control carries `required` for AT.
          <span aria-hidden="true" className="ml-1 text-[var(--sev-3)]">
            *
          </span>
        ) : null}
      </LabelPrimitive.Root>

      {children}

      {description ? (
        <p id={descriptionId} className="text-xs text-[var(--text-muted)]">
          {description}
        </p>
      ) : null}

      {error ? (
        // `role="alert"` so an error that appears after submission is announced without
        // the user having to go looking for it.
        <p id={errorId} role="alert" className="text-xs text-[var(--sev-3-fg)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** The shared control chrome: border, height, focus ring, invalid state. */
export const CONTROL_BASE =
  'w-full rounded-[var(--radius-default)] border bg-[var(--surface-base)] ' +
  'px-3 text-sm text-[var(--text-primary)] ' +
  'border-[var(--divider)] placeholder:text-[var(--text-muted)] ' +
  'aria-[invalid=true]:border-[var(--sev-3-border)] ' +
  'disabled:cursor-not-allowed disabled:opacity-50';
