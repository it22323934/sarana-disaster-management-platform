'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * GNDivisionPicker.
 *
 * Sri Lanka has roughly 14,000 GN divisions, so this is a search-as-you-type combobox
 * rather than a select. Two things about it are load-bearing:
 *
 * The **code is the identity and the name is only a label.** `LK-11-03-045` identifies a
 * division unambiguously; `Kadawatha` does not - several divisions share a name, and
 * transliteration between Sinhala, Tamil and English is not one-to-one. So the code is
 * always displayed, the code is what the value is, and matching runs over the code as
 * well as all three name scripts.
 *
 * **Matching is script-agnostic.** An officer typing in Sinhala must find a division
 * whose English name they have never seen, and vice versa, so the filter tests the query
 * against every locale's name rather than only the active one.
 *
 * It implements the ARIA combobox pattern by hand rather than through a listbox
 * primitive, because the value has to remain typeable: a dispatcher reading a code off a
 * radio needs to enter it directly without opening anything.
 */

import { localised, type Locale, type LocalisedText } from '@sarana/ts-shared/i18n';
import { useId, useMemo, useRef, useState } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';
import { CONTROL_BASE, Field } from '../primitives/field.js';

export interface GNDivision {
  /** `LK-DD-DD-DDD`. The identity. */
  readonly code: string;
  readonly name: LocalisedText;
  /** The DS division's name, shown as disambiguating context. */
  readonly dsName?: LocalisedText;
}

export interface GNDivisionPickerProps {
  readonly divisions: readonly GNDivision[];
  readonly value: string | null;
  readonly onChange: (code: string | null) => void;
  readonly locale: Locale;
  readonly label: string;
  readonly placeholder?: string;
  readonly description?: string;
  readonly error?: string;
  /** e.g. `(count) => \`${count} divisions\``. Announced as results narrow. */
  readonly resultsLabel: (count: number) => string;
  /** Cap on rendered options. 14,000 nodes would freeze the console. */
  readonly maxResults?: number;
  readonly className?: string;
}

/** Case-insensitive substring over the code and all three name scripts. */
function matches(division: GNDivision, query: string): boolean {
  if (query.length === 0) return true;
  const needle = query.toLocaleLowerCase();
  if (division.code.toLocaleLowerCase().includes(needle)) return true;
  return (['si', 'ta', 'en'] as const).some((locale) =>
    division.name[locale].toLocaleLowerCase().includes(needle),
  );
}

export function GNDivisionPicker({
  divisions,
  value,
  onChange,
  locale,
  label,
  placeholder,
  description,
  error,
  resultsLabel,
  maxResults = 50,
  className,
}: GNDivisionPickerProps) {
  const baseId = useId();
  const inputId = `${baseId}-input`;
  const listId = `${baseId}-list`;
  const inputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const results = useMemo(
    () => divisions.filter((division) => matches(division, query)).slice(0, maxResults),
    [divisions, query, maxResults],
  );

  const selected = divisions.find((division) => division.code === value) ?? null;

  function commit(division: GNDivision): void {
    onChange(division.code);
    setQuery('');
    setOpen(false);
    inputRef.current?.blur();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((index) => {
        const next = event.key === 'ArrowDown' ? index + 1 : index - 1;
        // Wraps, because a dispatcher holding the arrow key should not stall silently at
        // the end of a list they cannot see the bottom of.
        if (next < 0) return Math.max(0, results.length - 1);
        if (next >= results.length) return 0;
        return next;
      });
      return;
    }
    if (event.key === 'Enter' && open) {
      const division = results[activeIndex];
      if (division) {
        event.preventDefault();
        commit(division);
      }
      return;
    }
    if (event.key === 'Escape') {
      setOpen(false);
    }
  }

  return (
    <Field label={label} htmlFor={inputId} description={description} error={error}>
      <div className={cn('relative', className)}>
        <input
          ref={inputRef}
          id={inputId}
          role="combobox"
          type="text"
          autoComplete="off"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && results[activeIndex] ? `${baseId}-${activeIndex}` : undefined}
          aria-invalid={error ? true : undefined}
          placeholder={placeholder}
          value={open ? query : (selected ? `${selected.code} ${localised(selected.name, locale)}` : '')}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            // Deferred so a click on an option lands before the list unmounts.
            setTimeout(() => setOpen(false), 120);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setActiveIndex(0);
            setOpen(true);
          }}
          onKeyDown={onKeyDown}
          className={cn(CONTROL_BASE, 'h-11', FOCUS_RING)}
        />

        {/* Announced as the list narrows, so a screen reader user knows whether to keep
            typing. Polite: it fires on every keystroke. */}
        <span role="status" aria-live="polite" className="sr-only">
          {open ? resultsLabel(results.length) : ''}
        </span>

        {open ? (
          <ul
            id={listId}
            role="listbox"
            aria-label={label}
            className={cn(
              'absolute z-[var(--z-overlay)] mt-1 max-h-72 w-full overflow-y-auto',
              'rounded-[var(--radius-default)] border border-[var(--divider)]',
              'bg-[var(--surface-raised)] shadow-[var(--shadow-overlay)]',
            )}
          >
            {results.map((division, index) => (
              <li
                key={division.code}
                id={`${baseId}-${index}`}
                role="option"
                aria-selected={index === activeIndex}
                onMouseDown={() => commit(division)}
                onMouseEnter={() => setActiveIndex(index)}
                className={cn(
                  'flex min-h-[var(--touch-target-min)] cursor-pointer flex-col justify-center',
                  'px-3 py-1.5',
                  index === activeIndex && 'bg-[var(--surface-card)]',
                )}
              >
                <span className="flex items-baseline gap-2">
                  <span
                    data-sarana-datum=""
                    className="font-mono text-2xs text-[var(--text-muted)]"
                  >
                    {division.code}
                  </span>
                  <span className="text-sm text-[var(--text-primary)]">
                    {localised(division.name, locale)}
                  </span>
                </span>
                {division.dsName ? (
                  <span className="text-2xs text-[var(--text-muted)]">
                    {localised(division.dsName, locale)}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Field>
  );
}
