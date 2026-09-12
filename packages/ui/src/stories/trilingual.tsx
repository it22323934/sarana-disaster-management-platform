/**
 * The trilingual story harness.
 *
 * Every component in this library gets a story that renders it three times - once per
 * script - side by side. Rendering the three separately, behind a locale toolbar, is what
 * lets a Tamil layout bug survive review: nobody switches the toolbar. Side by side, a
 * label that wraps in Tamil and not in English is visible in the same glance.
 *
 * The `lang` attribute on each panel is what selects the Noto face through the `:lang()`
 * rules in `tokens.css`, so these panels also prove the per-script metrics are wired -
 * if Sinhala renders in the Latin face here, the token pipeline is broken.
 */

import { LOCALE_NAMES, type Locale } from '@sarana/ts-shared/i18n';
import type { ReactNode } from 'react';

import { STORY_LOCALES } from './fixtures.js';

const LANG_TAGS: Record<Locale, string> = { si: 'si-LK', ta: 'ta-LK', en: 'en-LK' };

export interface TrilingualProps {
  /** Rendered once per locale. */
  readonly render: (locale: Locale) => ReactNode;
  /**
   * Constrains each panel, in px, so a story reproduces the width the component actually
   * gets in the app. A component given infinite width never overflows and the story
   * proves nothing.
   */
  readonly width?: number;
}

export function Trilingual({ render, width = 320 }: TrilingualProps) {
  return (
    <div className="flex flex-wrap items-start gap-6">
      {STORY_LOCALES.map((locale) => (
        <section
          key={locale}
          lang={LANG_TAGS[locale]}
          data-story-locale={locale}
          style={{ width }}
          className="flex flex-col gap-2"
        >
          <h3 className="text-2xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
            {LOCALE_NAMES[locale]}
          </h3>
          {/* The border marks the slot the component has to fit inside. Anything
              crossing it in one script and not another is the bug these stories exist
              to surface. */}
          <div className="rounded-[var(--radius-default)] border border-dashed border-[var(--divider)] p-3">
            {render(locale)}
          </div>
        </section>
      ))}
    </div>
  );
}

/** A dark-surface frame, for components whose home is the operations console. */
export function OnDark({ children }: { readonly children: ReactNode }) {
  return (
    <div
      data-theme="dark"
      className="rounded-[var(--radius-surface)] bg-[var(--surface-base)] p-6 text-[var(--text-primary)]"
    >
      {children}
    </div>
  );
}

/** A light-surface frame, for the public dashboard. */
export function OnLight({ children }: { readonly children: ReactNode }) {
  return (
    <div
      data-theme="light"
      className="rounded-[var(--radius-surface)] bg-[var(--surface-base)] p-6 text-[var(--text-primary)]"
    >
      {children}
    </div>
  );
}
