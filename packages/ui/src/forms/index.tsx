'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * Form bindings: react-hook-form + zod, the trilingual field, and the offline-aware
 * submit.
 *
 * `react-hook-form` and `zod` are peer dependencies so the app owns one instance of each.
 * Two copies of react-hook-form in a tree produce a form whose context resolves to the
 * wrong provider, and the symptom is a field that never validates.
 */

import { zodResolver } from '@hookform/resolvers/zod';
import { LOCALES, LOCALE_NAMES, type Locale, type LocalisedText } from '@sarana/ts-shared/i18n';
import { useState, type ReactNode } from 'react';
import {
  useForm,
  type DefaultValues,
  type FieldValues,
  type UseFormReturn,
} from 'react-hook-form';
import type { ZodType } from 'zod';

import { cn } from '../lib/cn.js';
import { Button } from '../primitives/button.js';
import { Input } from '../primitives/input.js';
import { Textarea } from '../primitives/textarea.js';
import { TranslationCompleteness } from '../domain/localised-text.js';

/**
 * A form validated by the same zod schema the API uses.
 *
 * The schemas live in `@sarana/ts-shared/schemas` and are shared with the client, so a
 * field that the server would reject is rejected here with the same message rather than
 * with a second, drifting copy of the rule.
 */
export function useSaranaForm<Values extends FieldValues>(options: {
  schema: ZodType<Values>;
  defaultValues: DefaultValues<Values>;
}): UseFormReturn<Values> {
  return useForm<Values>({
    resolver: zodResolver(options.schema) as never,
    defaultValues: options.defaultValues,
    // Validate on blur rather than on change: an error appearing under a field while
    // someone is still typing their third character is noise, and on a handset it moves
    // the layout under their thumb.
    mode: 'onBlur',
  });
}

export interface TrilingualFieldProps {
  readonly label: string;
  readonly value: Partial<LocalisedText>;
  readonly onChange: (value: Partial<LocalisedText>) => void;
  /** Renders textareas instead of inputs. For alert bodies and grievance narratives. */
  readonly multiline?: boolean;
  readonly description?: ReactNode;
  readonly errors?: Partial<Record<Locale, string>>;
  /** Localised strings for the completeness indicator. */
  readonly completeLabel: string;
  readonly incompleteLabel: (missing: string) => string;
  readonly className?: string;
}

/**
 * One field, three scripts, all required.
 *
 * All three inputs are visible at once rather than behind tabs. A tabbed trilingual
 * field is how a record gets saved with two languages filled in: the third tab is out of
 * sight, the form submits, and the completeness check becomes the only thing standing
 * between that record and a citizen who cannot read it. Here the gap is on screen.
 *
 * Each input carries its own `lang`, so it renders in the right face and a screen reader
 * announces it in the right voice while it is being typed.
 */
export function TrilingualField({
  label,
  value,
  onChange,
  multiline = false,
  description,
  errors,
  completeLabel,
  incompleteLabel,
  className,
}: TrilingualFieldProps) {
  const present = LOCALES.filter((locale) => (value[locale] ?? '').trim().length > 0);
  const Control = multiline ? Textarea : Input;

  return (
    <fieldset className={cn('flex flex-col gap-3', className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <legend className="text-sm font-medium text-[var(--text-primary)]">{label}</legend>
        <TranslationCompleteness
          present={present}
          completeLabel={completeLabel}
          incompleteLabel={incompleteLabel}
        />
      </div>
      {description ? (
        <p className="text-xs text-[var(--text-muted)]">{description}</p>
      ) : null}

      {LOCALES.map((locale) => (
        <Control
          key={locale}
          label={LOCALE_NAMES[locale]}
          lang={locale === 'en' ? 'en-LK' : `${locale}-LK`}
          required
          value={value[locale] ?? ''}
          error={errors?.[locale]}
          onChange={(event: { target: { value: string } }) =>
            onChange({ ...value, [locale]: event.target.value })
          }
        />
      ))}
    </fieldset>
  );
}

export interface OfflineSubmitProps {
  readonly online: boolean;
  readonly submitting: boolean;
  /** Label when the submit will reach the server now. */
  readonly submitLabel: string;
  /** Label when it will be queued locally, e.g. "Save and send when online". */
  readonly queueLabel: string;
  /** Explains what queuing means. Rendered whenever offline, not on hover. */
  readonly queueExplanation: string;
  readonly disabled?: boolean;
  readonly className?: string;
}

/**
 * A submit button that tells the truth about where the data is going.
 *
 * Offline, it does not say "Submit" and fail, and it does not say "Submit" and silently
 * succeed into a local queue. It says the write will be held and sent later, because a
 * GN officer who believes an assessment reached Colombo will not go back and check.
 */
export function OfflineSubmit({
  online,
  submitting,
  submitLabel,
  queueLabel,
  queueExplanation,
  disabled,
  className,
}: OfflineSubmitProps) {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <Button
        type="submit"
        variant="primary"
        size="lg"
        busy={submitting}
        busyLabel={online ? submitLabel : queueLabel}
        disabled={disabled}
      >
        {online ? submitLabel : queueLabel}
      </Button>
      {!online ? (
        <p role="status" className="text-xs text-[var(--pending)]">
          {queueExplanation}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Guards a form against a double submit.
 *
 * Every POST that creates or moves money or dispatches carries an `Idempotency-Key`, so
 * a duplicate is safe on the server. This is the client half: it stops the second request
 * being made at all, which is what keeps the operator from seeing two confirmations and
 * wondering which one counted.
 */
export function useSubmitOnce(handler: () => Promise<void>): {
  readonly submitting: boolean;
  readonly submit: () => Promise<void>;
} {
  const [submitting, setSubmitting] = useState(false);

  return {
    submitting,
    submit: async () => {
      if (submitting) return;
      setSubmitting(true);
      try {
        await handler();
      } finally {
        setSubmitting(false);
      }
    },
  };
}
