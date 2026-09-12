'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * Checkbox, RadioGroup and Switch.
 *
 * Switch and Checkbox are not interchangeable, and which one a surface uses is a
 * statement about when the change lands: a Switch takes effect immediately, a Checkbox
 * takes effect on submit. Getting that backwards means an operator toggles something
 * they believed they were staging, and on this platform the toggle might be
 * "bypass quiet hours".
 *
 * In all three, the whole row is the hit target rather than the 18px box. A 44px row is
 * reachable with a wet finger; an 18px square is not.
 */

import * as CheckboxPrimitive from '@radix-ui/react-checkbox';
import * as LabelPrimitive from '@radix-ui/react-label';
import * as RadioGroupPrimitive from '@radix-ui/react-radio-group';
import * as SwitchPrimitive from '@radix-ui/react-switch';
import {
  forwardRef,
  useId,
  type ComponentPropsWithoutRef,
  type ElementRef,
  type ReactNode,
} from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';

const BOX =
  'grid size-[18px] shrink-0 place-items-center border border-[var(--divider)] ' +
  'bg-[var(--surface-base)] disabled:cursor-not-allowed disabled:opacity-50';

const ROW = 'flex min-h-[var(--touch-target-min)] items-start gap-3 py-2';

export interface CheckboxProps
  extends Omit<ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>, 'children'> {
  readonly label: ReactNode;
  readonly description?: ReactNode;
}

export const Checkbox = forwardRef<ElementRef<typeof CheckboxPrimitive.Root>, CheckboxProps>(
  function Checkbox({ label, description, className, id, ...rest }, ref) {
    const generated = useId();
    const controlId = id ?? `sarana-${generated}`;
    const descriptionId = description ? `${controlId}-description` : undefined;

    return (
      <div className={ROW}>
        <CheckboxPrimitive.Root
          ref={ref}
          id={controlId}
          aria-describedby={descriptionId}
          className={cn(
            BOX,
            'mt-0.5 rounded-[var(--radius-cell)]',
            'data-[state=checked]:border-[var(--signal-500)]',
            'data-[state=checked]:bg-[var(--signal-500)]',
            FOCUS_RING,
            className,
          )}
          {...rest}
        >
          <CheckboxPrimitive.Indicator className="text-[var(--on-signal)]">
            <svg viewBox="0 0 12 12" className="size-3" aria-hidden="true">
              <path
                d="M2.5 6.5 5 9l4.5-5.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </CheckboxPrimitive.Indicator>
        </CheckboxPrimitive.Root>

        <div className="flex flex-col gap-0.5">
          <LabelPrimitive.Root
            htmlFor={controlId}
            className="cursor-pointer text-sm text-[var(--text-primary)]"
          >
            {label}
          </LabelPrimitive.Root>
          {description ? (
            <span id={descriptionId} className="text-xs text-[var(--text-muted)]">
              {description}
            </span>
          ) : null}
        </div>
      </div>
    );
  },
);

export interface RadioOption {
  readonly value: string;
  readonly label: ReactNode;
  readonly description?: ReactNode;
  readonly disabled?: boolean;
}

export interface RadioGroupProps
  extends Omit<ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Root>, 'children'> {
  /**
   * The question the options answer. Required, and rendered as a real legend.
   *
   * A radio group with no legend is the commonest way a form becomes unusable with a
   * screen reader: the options are read out with no indication of what they are for.
   */
  readonly legend: ReactNode;
  readonly options: readonly RadioOption[];
}

export const RadioGroup = forwardRef<
  ElementRef<typeof RadioGroupPrimitive.Root>,
  RadioGroupProps
>(function RadioGroup({ legend, options, className, ...rest }, ref) {
  const groupId = useId();

  return (
    <fieldset className="flex flex-col gap-2">
      <legend
        id={`${groupId}-legend`}
        className="mb-1 text-sm font-medium text-[var(--text-primary)]"
      >
        {legend}
      </legend>
      <RadioGroupPrimitive.Root
        ref={ref}
        aria-labelledby={`${groupId}-legend`}
        className={cn('flex flex-col', className)}
        {...rest}
      >
        {options.map((option) => {
          const itemId = `${groupId}-${option.value}`;
          const descriptionId = option.description ? `${itemId}-description` : undefined;
          return (
            <div key={option.value} className={ROW}>
              <RadioGroupPrimitive.Item
                id={itemId}
                value={option.value}
                disabled={option.disabled}
                aria-describedby={descriptionId}
                className={cn(
                  BOX,
                  'mt-0.5 rounded-full data-[state=checked]:border-[var(--signal-500)]',
                  FOCUS_RING,
                )}
              >
                <RadioGroupPrimitive.Indicator className="size-2.5 rounded-full bg-[var(--signal-500)]" />
              </RadioGroupPrimitive.Item>
              <div className="flex flex-col gap-0.5">
                <LabelPrimitive.Root
                  htmlFor={itemId}
                  className="cursor-pointer text-sm text-[var(--text-primary)]"
                >
                  {option.label}
                </LabelPrimitive.Root>
                {option.description ? (
                  <span id={descriptionId} className="text-xs text-[var(--text-muted)]">
                    {option.description}
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
      </RadioGroupPrimitive.Root>
    </fieldset>
  );
});

export interface SwitchProps
  extends Omit<ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>, 'children'> {
  readonly label: ReactNode;
  readonly description?: ReactNode;
}

export const Switch = forwardRef<ElementRef<typeof SwitchPrimitive.Root>, SwitchProps>(
  function Switch({ label, description, className, id, ...rest }, ref) {
    const generated = useId();
    const controlId = id ?? `sarana-${generated}`;
    const descriptionId = description ? `${controlId}-description` : undefined;

    return (
      <div className="flex min-h-[var(--touch-target-min)] items-center justify-between gap-4 py-2">
        <div className="flex flex-col gap-0.5">
          <LabelPrimitive.Root
            htmlFor={controlId}
            className="cursor-pointer text-sm text-[var(--text-primary)]"
          >
            {label}
          </LabelPrimitive.Root>
          {description ? (
            <span id={descriptionId} className="text-xs text-[var(--text-muted)]">
              {description}
            </span>
          ) : null}
        </div>
        <SwitchPrimitive.Root
          ref={ref}
          id={controlId}
          aria-describedby={descriptionId}
          className={cn(
            'relative h-6 w-11 shrink-0 rounded-full border border-[var(--divider)]',
            'bg-[var(--surface-raised)] transition-colors duration-[var(--motion-state)]',
            'data-[state=checked]:border-[var(--signal-500)]',
            'data-[state=checked]:bg-[var(--signal-500)]',
            'disabled:cursor-not-allowed disabled:opacity-50',
            FOCUS_RING,
            className,
          )}
          {...rest}
        >
          <SwitchPrimitive.Thumb
            className={cn(
              'block size-[18px] translate-x-0.5 rounded-full bg-[var(--text-primary)]',
              'transition-transform duration-[var(--motion-state)]',
              'data-[state=checked]:translate-x-[22px] data-[state=checked]:bg-[var(--on-signal)]',
            )}
          />
        </SwitchPrimitive.Root>
      </div>
    );
  },
);
