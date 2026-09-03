'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * Textarea.
 *
 * Minimum four rows. Citizen report descriptions and grievance narratives arrive in
 * Sinhala and Tamil, which set taller than Latin at the same size; a two-row box that
 * looks roomy in English shows one and a half lines of Sinhala.
 */

import { forwardRef, type ReactNode, type TextareaHTMLAttributes } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';
import { CONTROL_BASE, Field, useFieldIds } from './field.js';

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  readonly label: ReactNode;
  readonly description?: ReactNode;
  readonly error?: ReactNode;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, description, error, className, id, required, rows = 4, ...rest },
  ref,
) {
  const ids = useFieldIds({
    hasDescription: Boolean(description),
    hasError: Boolean(error),
    id,
  });

  return (
    <Field
      label={label}
      htmlFor={ids.controlId}
      description={description}
      error={error}
      descriptionId={ids.descriptionId}
      errorId={ids.errorId}
      required={required}
    >
      <textarea
        ref={ref}
        id={ids.controlId}
        rows={rows}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={ids.describedBy}
        className={cn(CONTROL_BASE, 'py-2 leading-[var(--leading-sm)]', FOCUS_RING, className)}
        {...rest}
      />
    </Field>
  );
});
