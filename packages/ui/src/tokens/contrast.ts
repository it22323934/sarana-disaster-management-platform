/**
 * WCAG 2.2 relative luminance and contrast maths.
 *
 * Lives in the token layer rather than in a test helper because the contrast gate runs
 * in CI, in Storybook's a11y panel and in the token generator, and three copies of this
 * arithmetic would eventually disagree about which one the design system is held to.
 *
 * Only sRGB hex is accepted. The platform has one colour space and every token is
 * written as a six-digit hex, so a parser that also accepted `rgb()` or `hsl()` would
 * be dead code with a maintenance cost.
 */

export type Hex = `#${string}`;

/** WCAG 2.2 SC 1.4.3: normal-size body text against its background. */
export const AA_TEXT = 4.5;

/** WCAG 2.2 SC 1.4.3: text at 18.66px bold or 24px regular and above. */
export const AA_LARGE_TEXT = 3;

/**
 * WCAG 2.2 SC 1.4.11: borders, focus rings and any boundary a reader needs in order to
 * identify a control or its state. Lower than the text floor because the eye resolves a
 * shape's edge at a lower contrast than it resolves a glyph.
 */
export const AA_NON_TEXT = 3;

const HEX_PATTERN = /^#[0-9a-fA-F]{6}$/;

export class InvalidHexError extends Error {
  constructor(readonly value: string) {
    super(`not a six-digit sRGB hex colour: ${value}`);
    this.name = 'InvalidHexError';
  }
}

/** Split a hex colour into 0-255 channels. */
export function toRgb(hex: string): readonly [number, number, number] {
  if (!HEX_PATTERN.test(hex)) throw new InvalidHexError(hex);
  const body = hex.slice(1);
  return [
    Number.parseInt(body.slice(0, 2), 16),
    Number.parseInt(body.slice(2, 4), 16),
    Number.parseInt(body.slice(4, 6), 16),
  ];
}

/** Undo the sRGB transfer function for one channel. */
function linearise(channel: number): number {
  const scaled = channel / 255;
  return scaled <= 0.04045 ? scaled / 12.92 : Math.pow((scaled + 0.055) / 1.055, 2.4);
}

/** WCAG 2.2 relative luminance, 0 (black) to 1 (white). */
export function relativeLuminance(hex: string): number {
  const [r, g, b] = toRgb(hex).map(linearise) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * Contrast ratio between two colours, 1 to 21.
 *
 * Order-independent by construction, which matters: a pairing table that produced a
 * different answer for (fg, bg) than for (bg, fg) would let a failing pair pass by
 * being written the other way round.
 */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const [lighter, darker] = la > lb ? [la, lb] : [lb, la];
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Round a ratio the way the gate reports it.
 *
 * Two decimals, rounded *down*, so a pairing that computes to 4.4999 is reported as
 * 4.49 and fails rather than being rounded up to the floor it does not meet.
 */
export function reportRatio(ratio: number): number {
  return Math.floor(ratio * 100) / 100;
}

export function meets(a: string, b: string, floor: number): boolean {
  return contrastRatio(a, b) >= floor;
}
