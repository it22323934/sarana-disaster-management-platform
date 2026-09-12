/**
 * The design system, in React Native units.
 *
 * Nothing here invents a value. Every number is imported from `@sarana/ui/tokens`, which
 * is the single source of truth for the console, the public dashboard and this app -
 * a fourth table of colours that drifts from the other three is exactly what a design
 * system exists to prevent.
 *
 * What this module does add is the two things the web tokens cannot express:
 *
 *   - **React Native line heights are absolute, not multipliers.** The web scale is
 *     unitless; here it has to be multiplied out against the rendered size, per script.
 *   - **Dynamic type.** The brief requires layouts to hold at 200%. `fontScale` comes
 *     from the OS and every size in the app passes through it rather than being used
 *     raw, so a 200% setting enlarges the text instead of clipping it.
 */

import { PixelRatio, Platform } from 'react-native';
import type { Locale } from '@sarana/ts-shared/i18n';

import { overrides } from '../debug/bridge.js';

import {
  DIVIDER,
  RADIUS,
  SEVERITY,
  SIGNAL,
  SPACE,
  SURFACES as UI_SURFACES,
  TOUCH_TARGET_MIN,
  TOUCH_TARGET_SOS,
  TYPE_SCALE,
  VERIFY,
  lineHeightFor,
  sizeFor,
  type Surface as SurfaceScheme,
  type TypeSize,
} from '@sarana/ui/tokens';

export { RADIUS, SPACE, TOUCH_TARGET_MIN, TOUCH_TARGET_SOS, TYPE_SCALE };
export type { SurfaceScheme, TypeSize };

/**
 * The interface accent, re-exported so a screen never writes the hex itself.
 *
 * Nine screens had `#0E7C86` typed into them directly. That is the teal the palette used
 * to carry, and when the palette moved to azure every one of those screens stayed teal -
 * a handset showing one accent and the console another, with nothing failing anywhere to
 * say so. A hardcoded colour does not drift loudly; it drifts silently, which is the
 * failure this module's opening line exists to prevent.
 *
 * `ACCENT_ON` is the label colour for text sitting on that fill, and it is white rather
 * than `ON_FILL`: `ON_FILL` is the warm-tinted white reserved for severity fills, and
 * using it here would put a hazard's text colour on an ordinary button.
 */
export const ACCENT = SIGNAL[500];
export const ACCENT_ON = '#FFFFFF';

/**
 * The accent one step deeper, for a fill drawn on the dark scheme.
 *
 * `IncidentTypeGrid` selects with this on dark so the chosen tile reads as pressed rather
 * than as something glowing above the surface behind it.
 */
export const ACCENT_DEEP = SIGNAL[600];

/**
 * The ceiling on dynamic type.
 *
 * The brief asks for 200% and stops there. Android and iOS both allow larger settings for
 * users with severe low vision, and honouring 300% on a form with three inputs and a map
 * produces a screen that cannot be completed at all. Capping and then saying so on the
 * accessibility screen is the honest answer; silently clipping is not.
 */
export const MAX_FONT_SCALE = 2;

/**
 * The OS text size setting, clamped.
 *
 * `overrides.fontScale` is null in every build that is not a development one, so this is
 * the platform value everywhere it matters. It exists because Maestro drives the app and
 * not the settings app, and the 200% case is one the brief asks for by name.
 */
export function fontScale(): number {
  return Math.min(overrides.fontScale ?? PixelRatio.getFontScale(), MAX_FONT_SCALE);
}

export interface TypeStyle {
  readonly fontSize: number;
  readonly lineHeight: number;
  readonly fontFamily?: string;
  readonly letterSpacing?: number;
}

/**
 * The font family for a script.
 *
 * Not the web stack. React Native takes one family name, and the three faces are bundled
 * in the binary rather than fetched - the moment a citizen most needs to read a warning
 * is the moment the network is worst. `undefined` means the platform default, which is
 * what English uses: San Francisco and Roboto are both better Latin faces on their own
 * platform than anything that could be bundled.
 */
export function fontFamilyFor(locale: Locale): string | undefined {
  if (locale === 'si') return 'NotoSansSinhala';
  if (locale === 'ta') return 'NotoSansTamil';
  return undefined;
}

/**
 * One type step, rendered for one locale at the current OS text size.
 *
 * `sizeFor` and `lineHeightFor` carry the per-script tuning: Sinhala needs the larger
 * leading because its ascender/descender range is the widest of the three, and at Latin
 * leading the ේ of one line touches the ු of the line above.
 */
export function type(size: TypeSize, locale: Locale, scale = fontScale()): TypeStyle {
  const fontSize = Math.round(sizeFor(size, locale) * scale);
  return {
    fontSize,
    // Absolute px, because React Native has no unitless line-height.
    lineHeight: Math.round(fontSize * lineHeightFor(size, locale)),
    fontFamily: fontFamilyFor(locale),
    // Tracking is Latin-only: Sinhala and Tamil glyphs join, and letter-spacing breaks
    // the join. The web tokens scope this with `:lang(en)`; here it is a branch.
    letterSpacing: locale === 'en' && (size === '2xl' || size === '3xl') ? -0.5 : undefined,
  };
}

/**
 * The minimum height a tappable thing may have, at the current text size.
 *
 * 44 is the floor from the design system, and it grows with the text: a control sized to
 * fit 16px text has to fit 32px text too, or the label is clipped at the setting that
 * exists to make it readable.
 */
export function touchTarget(kind: 'min' | 'sos' = 'min', scale = fontScale()): number {
  const base = kind === 'sos' ? TOUCH_TARGET_SOS : TOUCH_TARGET_MIN;
  return Math.round(base * Math.max(1, scale * 0.75));
}

export interface Surface {
  readonly base: string;
  readonly raised: string;
  readonly card: string;
  readonly text: string;
  readonly muted: string;
  readonly divider: string;
}

export const SURFACES: Record<SurfaceScheme, Surface> = {
  light: { ...UI_SURFACES.light, divider: DIVIDER.light },
  dark: { ...UI_SURFACES.dark, divider: DIVIDER.dark },
};

export type StatusTone = 'synced' | 'syncing' | 'offline' | 'attention';

/**
 * The four status-strip tones, resolved to colours.
 *
 * Colour is never the only signal - `STATUS_GLYPH` carries the same information as a
 * shape, because the strip is read at a glance in rain by someone who may be colour-blind
 * and is definitely not looking closely.
 */
export function statusColours(
  tone: StatusTone,
  scheme: SurfaceScheme,
): { background: string; foreground: string } {
  const surface = SURFACES[scheme];
  switch (tone) {
    case 'synced':
      return { background: surface.raised, foreground: VERIFY[500] };
    case 'syncing':
      return { background: surface.raised, foreground: SIGNAL[500] };
    case 'offline':
      return { background: surface.card, foreground: surface.muted };
    case 'attention':
      // Severity 3's fill, which is the same red the console uses for a life-safety row.
      return { background: SEVERITY[3][scheme].bg, foreground: SEVERITY[3][scheme].fg };
  }
}

/** Elevation, expressed the way each platform actually does it. */
export const SHADOW = Platform.select({
  android: { elevation: 2 },
  default: {
    shadowColor: '#000',
    shadowOpacity: 0.08,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
  },
}) as Record<string, unknown>;
