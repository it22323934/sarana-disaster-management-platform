'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * LocalisedText, LanguageSwitcher and TranslationCompleteness.
 *
 * The trilingual invariant, made structural.
 *
 * `LocalisedText` cannot render a bare string. That is the whole point of it: a component
 * that accepted `string | LocalisedText` would be used with a string on the first busy
 * afternoon, and the record it rendered would reach a Tamil-speaking citizen in Sinhala.
 * The type refuses, so the failure happens at the keyboard rather than in a division.
 *
 * On 28 Nov 2025 the DMC press conference for Cyclone Ditwah went out in Sinhala and
 * English only. That is the failure this file exists to make structurally impossible.
 */

import {
  LOCALES,
  LOCALE_NAMES,
  isLocalisedText,
  localised,
  type Locale,
  type LocalisedText as LocalisedTextValue,
} from '@sarana/ts-shared/i18n';
import type { ElementType, ReactNode } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';

/** BCP-47 tags. `lang` drives font selection and screen reader pronunciation. */
const LANG_TAGS: Record<Locale, string> = { si: 'si-LK', ta: 'ta-LK', en: 'en-LK' };

export interface LocalisedTextProps {
  /** All three locales required. There is no single-string overload and never will be. */
  readonly value: LocalisedTextValue;
  readonly locale: Locale;
  /** Defaults to `span`. Use `p`, `h2`, `li` where the surrounding markup needs it. */
  readonly as?: ElementType;
  readonly className?: string;
}

/**
 * Render one locale of a trilingual value, and set `lang` on the element.
 *
 * The `lang` attribute is not decoration. It selects the Noto face through the `:lang()`
 * rules in `tokens.css`, and it tells a screen reader which voice to use - a Tamil string
 * read by an English voice is not comprehensible.
 */
export function LocalisedText({ value, locale, as, className }: LocalisedTextProps) {
  const Component = as ?? 'span';

  if (!isLocalisedText(value)) {
    // Loud in development, and it still renders something rather than blanking a page
    // mid-incident. A payload that fails this is a server-side bug: the API contract
    // requires all three locales and a CHECK constraint enforces it in the database.
    if (process.env.NODE_ENV !== 'production') {
      console.error(
        'LocalisedText received a value that is not trilingual. All three of si, ta and ' +
          'en are required and non-empty. Value:',
        value,
      );
    }
    return (
      <Component
        className={cn('underline decoration-[var(--sev-2-border)] decoration-wavy', className)}
        data-sarana-incomplete-translation="true"
      >
        {typeof value === 'object' && value !== null
          ? ((value as Partial<LocalisedTextValue>)[locale] ?? '')
          : ''}
      </Component>
    );
  }

  return (
    <Component lang={LANG_TAGS[locale]} className={className}>
      {localised(value, locale)}
    </Component>
  );
}

export interface LanguageSwitcherProps {
  readonly locale: Locale;
  readonly onChange: (locale: Locale) => void;
  /** Names the group, e.g. "Language". Localised by the caller. */
  readonly label: string;
  readonly className?: string;
}

/**
 * The three languages, each written in its own script.
 *
 * Never translated, and never abbreviated to a flag or a two-letter code: a speaker
 * looking for their language finds it by its own name. Rendered as a radio group rather
 * than a select so all three are visible without opening anything - the switcher is most
 * needed by the person least able to read the interface they are currently in.
 */
export function LanguageSwitcher({
  locale,
  onChange,
  label,
  className,
}: LanguageSwitcherProps) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn('inline-flex rounded-[var(--radius-default)] border border-[var(--divider)]', className)}
    >
      {LOCALES.map((candidate) => (
        <button
          key={candidate}
          type="button"
          role="radio"
          lang={LANG_TAGS[candidate]}
          aria-checked={candidate === locale}
          onClick={() => onChange(candidate)}
          className={cn(
            'min-h-[var(--touch-target-min)] px-3 text-sm transition-colors',
            'duration-[var(--motion-state)] first:rounded-l-[var(--radius-default)]',
            'last:rounded-r-[var(--radius-default)]',
            candidate === locale
              ? 'bg-[var(--signal-500)] font-medium text-[var(--on-signal)]'
              : 'text-[var(--text-muted)] hover:bg-[var(--surface-raised)]',
            FOCUS_RING,
          )}
        >
          {LOCALE_NAMES[candidate]}
        </button>
      ))}
    </div>
  );
}

export interface TranslationCompletenessProps {
  /** Which locales this record actually has non-empty text for. */
  readonly present: readonly Locale[];
  /** Localised strings for the two states. Supplied by the caller's catalogue. */
  readonly completeLabel: string;
  readonly incompleteLabel: (missing: string) => string;
  readonly className?: string;
}

/**
 * Whether a record is publishable, and if not, in which language it is missing.
 *
 * Used on template and alert drafts. This is the affordance that stops a
 * two-language alert from being signed off: the reviewer sees which script is absent
 * before they reach the button, not after.
 */
export function TranslationCompleteness({
  present,
  completeLabel,
  incompleteLabel,
  className,
}: TranslationCompletenessProps) {
  const missing = LOCALES.filter((locale) => !present.includes(locale));
  const complete = missing.length === 0;

  return (
    <span
      // `status` rather than `alert`: it is a standing fact about the record, not an
      // event, and an alert role would interrupt a reviewer mid-sentence on every render.
      role="status"
      className={cn(
        'inline-flex items-center gap-1.5 text-xs',
        complete ? 'text-[var(--verified)]' : 'text-[var(--sev-2-fg)]',
        className,
      )}
    >
      <ShapeMark complete={complete} />
      {complete
        ? completeLabel
        : incompleteLabel(missing.map((locale) => LOCALE_NAMES[locale]).join(', '))}
    </span>
  );
}

/** A tick or a bar, so the state is not carried by green-versus-amber alone. */
function ShapeMark({ complete }: { readonly complete: boolean }): ReactNode {
  return (
    <svg viewBox="0 0 12 12" className="size-3 shrink-0" aria-hidden="true">
      <path
        d={complete ? 'M2.5 6.5 5 9l4.5-5.5' : 'M6 2.5v5M6 9.2v.3'}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
