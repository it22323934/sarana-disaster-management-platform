/**
 * Text input.
 *
 * `inputMode` is exposed and used deliberately across the apps: a GN officer entering a
 * cost estimate on a handset should get the numeric keypad, and an NIC field should not
 * get autocorrect. Getting this wrong is not cosmetic - it is the difference between a
 * form that can be completed standing in a field and one that cannot.
 */

import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';
import { CONTROL_BASE, Field, useFieldIds } from './field.js';

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  readonly label: ReactNode;
  readonly description?: ReactNode;
  readonly error?: ReactNode;
  /** Rendered in the mono stack with tabular figures. For codes, amounts, coordinates. */
  readonly datum?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, description, error, datum = false, className, id, required, ...rest },
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
      <input
        ref={ref}
        id={ids.controlId}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={ids.describedBy}
        {...(datum ? { 'data-sarana-datum': '' } : {})}
        className={cn(CONTROL_BASE, 'h-11', FOCUS_RING, className)}
        {...rest}
      />
    </Field>
  );
});
