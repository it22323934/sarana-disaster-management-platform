/**
 * SeverityPill and ImpactClassBadge.
 *
 * The component the whole colour system exists for, and the one place the reserved ramp
 * is allowed on screen as a chip.
 *
 * It renders three things every time and offers no way to render fewer: the colour, a
 * shape, and the word. `tokens.test.ts` measures why - ochre, amber and red at one tint
 * lightness land within 1.06:1 of each other in greyscale, so a reader with a colour
 * vision deficiency cannot separate an advisory chip from a watch chip by its fill at
 * all. There is no `showLabel={false}`, no icon-only variant and no compact mode that
 * drops the shape. A caller who needs something smaller uses `SeverityDot`, which is
 * explicitly documented as needing a label beside it.
 */

import type { Locale } from '@sarana/ts-shared/i18n';

import { cn } from '../lib/cn.js';
import {
  SEVERITY,
  SEVERITY_LABELS,
  type SeverityLevel,
  type SeverityShape,
} from '../tokens/severity.js';

/**
 * The five silhouettes, at 12px.
 *
 * Chosen to stay distinct in monochrome, which rules out the obvious
 * outline-triangle/filled-triangle pairing: at this size the fill is the only difference
 * and it is the first thing to disappear.
 */
const SHAPE_PATHS: Record<SeverityShape, string> = {
  circle: 'M6 1.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9Z',
  square: 'M2 2h8v8H2Z',
  triangle: 'M6 1.5 11 10.5H1Z',
  diamond: 'M6 1 11 6 6 11 1 6Z',
  octagon: 'M4 1h4l3 3v4l-3 3H4L1 8V4Z',
};

/**
 * Chip classes per level, written out in full.
 *
 * Not built by concatenation. Tailwind extracts utilities by scanning source for literal
 * class strings, so a class assembled at run time is never generated and the chip renders
 * with no background - and it fails silently, in the build, on the one component whose
 * colour is load-bearing.
 */
const CHIP_CLASSES: Record<SeverityLevel, string> = {
  0: 'border-[var(--sev-0-border)] bg-[var(--sev-0-bg)] text-[var(--sev-0-fg)]',
  1: 'border-[var(--sev-1-border)] bg-[var(--sev-1-bg)] text-[var(--sev-1-fg)]',
  2: 'border-[var(--sev-2-border)] bg-[var(--sev-2-bg)] text-[var(--sev-2-fg)]',
  3: 'border-[var(--sev-3-border)] bg-[var(--sev-3-bg)] text-[var(--sev-3-fg)]',
  4: 'border-[var(--sev-4-border)] bg-[var(--sev-4-bg)] text-[var(--sev-4-fg)]',
};

/** The marker colour on its own, for the dot. Literal for the same reason. */
const MARK_CLASSES: Record<SeverityLevel, string> = {
  0: 'text-[var(--sev-0-border)]',
  1: 'text-[var(--sev-1-border)]',
  2: 'text-[var(--sev-2-border)]',
  3: 'text-[var(--sev-3-border)]',
  4: 'text-[var(--sev-4-border)]',
};

export interface SeverityShapeMarkProps {
  readonly level: SeverityLevel;
  readonly className?: string;
}

/** The silhouette on its own. Always accompanied by a label - it is `aria-hidden`. */
export function SeverityShapeMark({ level, className }: SeverityShapeMarkProps) {
  return (
    <svg
      viewBox="0 0 12 12"
      className={cn('size-3 shrink-0', className)}
      aria-hidden="true"
      focusable="false"
    >
      <path d={SHAPE_PATHS[SEVERITY[level].shape]} fill="currentColor" />
    </svg>
  );
}

export interface SeverityPillProps {
  readonly level: SeverityLevel;
  readonly locale: Locale;
  /**
   * Overrides the standard word. Use only where the surface has a more specific one -
   * an alert's own headline, say. It is still a required string, so there is no path to
   * a pill without text.
   */
  readonly label?: string;
  readonly className?: string;
}

export function SeverityPill({ level, locale, label, className }: SeverityPillProps) {
  const token = SEVERITY[level];
  const text = label ?? SEVERITY_LABELS[level][locale];

  return (
    <span
      // The level is in the DOM as data, so a test or an export can read the grade
      // without parsing a colour.
      data-severity={level}
      data-severity-name={token.name}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1',
        'text-2xs font-medium leading-none',
        // Theme-aware: the CSS variables resolve per surface, so the same element is
        // correct on the dark console and on the light dashboard.
        CHIP_CLASSES[level],
        className,
      )}
    >
      <SeverityShapeMark level={level} />
      {text}
    </span>
  );
}

export interface SeverityDotProps {
  readonly level: SeverityLevel;
  /**
   * What the dot means, for assistive technology.
   *
   * Required, because a dot alone is exactly the colour-only encoding the pill exists to
   * prevent. Use this only where a visible label is already adjacent - a map marker with
   * a legend, a table row whose severity column is beside it.
   */
  readonly label: string;
  readonly className?: string;
}

export function SeverityDot({ level, label, className }: SeverityDotProps) {
  return (
    <span
      role="img"
      aria-label={label}
      data-severity={level}
      className={cn('inline-flex', MARK_CLASSES[level], className)}
    >
      <SeverityShapeMark level={level} />
    </span>
  );
}

/**
 * The forecast agent's impact class, 0-4.
 *
 * The same five-step grade as the severity ramp but a different thing: severity is what
 * a warning says, impact class is what the model predicts. They are shown side by side
 * on the forecast surface, so this renders as a square-cornered badge rather than a pill
 * - two identical chips carrying two different meanings is how an operator reads a
 * prediction as a warning.
 */
export interface ImpactClassBadgeProps {
  readonly impactClass: SeverityLevel;
  readonly locale: Locale;
  /** e.g. "Predicted impact". Localised by the caller, and always rendered. */
  readonly prefix: string;
  readonly className?: string;
}

export function ImpactClassBadge({
  impactClass,
  locale,
  prefix,
  className,
}: ImpactClassBadgeProps) {
  return (
    <span
      data-impact-class={impactClass}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-[var(--radius-cell)] border px-2 py-1',
        'text-2xs leading-none',
        CHIP_CLASSES[impactClass],
        className,
      )}
    >
      <SeverityShapeMark level={impactClass} />
      <span className="opacity-80">{prefix}</span>
      <span className="font-medium">{SEVERITY_LABELS[impactClass][locale]}</span>
    </span>
  );
}
