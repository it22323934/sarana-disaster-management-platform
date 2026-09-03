/**
 * Select.
 *
 * A listbox rather than a native `<select>`, because the options this platform shows are
 * routinely localised text that has to carry its own `lang` attribute - a GN division
 * name in Tamil inside a Sinhala interface renders in the wrong face otherwise, and a
 * native option element cannot be styled or marked up per item.
 *
 * The cost is that it now owns keyboard behaviour that the platform used to provide, so
 * it uses Radix rather than a hand-rolled listbox.
 */

import * as SelectPrimitive from '@radix-ui/react-select';
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef, type ReactNode } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';
import { CONTROL_BASE, Field, useFieldIds } from './field.js';

export interface SelectOption {
  readonly value: string;
  readonly label: ReactNode;
  /** BCP-47 tag for this option's text, when it differs from the interface locale. */
  readonly lang?: string;
  readonly disabled?: boolean;
}

export interface SelectProps
  extends Omit<ComponentPropsWithoutRef<typeof SelectPrimitive.Root>, 'children'> {
  readonly label: ReactNode;
  readonly options: readonly SelectOption[];
  readonly placeholder?: string;
  readonly description?: ReactNode;
  readonly error?: ReactNode;
  readonly id?: string;
  readonly className?: string;
}

export const Select = forwardRef<ElementRef<typeof SelectPrimitive.Trigger>, SelectProps>(
  function Select(
    { label, options, placeholder, description, error, className, id, required, ...rest },
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
        <SelectPrimitive.Root required={required} {...rest}>
          <SelectPrimitive.Trigger
            ref={ref}
            id={ids.controlId}
            aria-invalid={error ? true : undefined}
            aria-describedby={ids.describedBy}
            className={cn(
              CONTROL_BASE,
              'flex h-11 items-center justify-between gap-2 text-left',
              FOCUS_RING,
              className,
            )}
          >
            <SelectPrimitive.Value placeholder={placeholder} />
            <SelectPrimitive.Icon>
              <svg viewBox="0 0 12 12" className="size-3 opacity-60" aria-hidden="true">
                <path
                  d="m2.5 4.5 3.5 3.5 3.5-3.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </SelectPrimitive.Icon>
          </SelectPrimitive.Trigger>

          <SelectPrimitive.Portal>
            <SelectPrimitive.Content
              position="popper"
              sideOffset={4}
              className={cn(
                'z-[var(--z-overlay)] overflow-hidden rounded-[var(--radius-default)]',
                'border border-[var(--divider)] bg-[var(--surface-raised)]',
                'shadow-[var(--shadow-overlay)]',
                // Matching the trigger width keeps a long Tamil option from widening the
                // popup past the control it belongs to.
                'w-[var(--radix-select-trigger-width)]',
                'max-h-[min(24rem,var(--radix-select-content-available-height))]',
              )}
            >
              <SelectPrimitive.Viewport className="p-1">
                {options.map((option) => (
                  <SelectPrimitive.Item
                    key={option.value}
                    value={option.value}
                    disabled={option.disabled}
                    lang={option.lang}
                    className={cn(
                      'relative flex min-h-[var(--touch-target-min)] cursor-pointer',
                      'select-none items-center rounded-[var(--radius-cell)] py-2 pl-8 pr-3',
                      'text-sm text-[var(--text-primary)] outline-none',
                      'data-[highlighted]:bg-[var(--surface-card)]',
                      'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50',
                    )}
                  >
                    <span className="absolute left-2 grid place-items-center">
                      <SelectPrimitive.ItemIndicator>
                        <svg
                          viewBox="0 0 12 12"
                          className="size-3 text-[var(--text-accent)]"
                          aria-hidden="true"
                        >
                          <path
                            d="M2.5 6.5 5 9l4.5-5.5"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.8"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </SelectPrimitive.ItemIndicator>
                    </span>
                    <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
                  </SelectPrimitive.Item>
                ))}
              </SelectPrimitive.Viewport>
            </SelectPrimitive.Content>
          </SelectPrimitive.Portal>
        </SelectPrimitive.Root>
      </Field>
    );
  },
);
