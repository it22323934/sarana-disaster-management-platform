/**
 * Every colour pairing the design system actually renders, and the floor each must meet.
 *
 * "Every token pairing" cannot mean the raw cross product: `--sev-1-fg` on `--sev-3-bg`
 * is not a thing this system draws, and a gate that measured it would spend its budget
 * failing combinations nobody can reach. So the contract is declared instead, and a
 * second check - `unpairedTokens()` - proves the declaration is exhaustive by failing on
 * any colour token that appears in no pairing at all. A new token cannot be added and
 * quietly escape the gate; it has to be paired, or exempted with a reason.
 *
 * Two floors, because WCAG has two: 4.5:1 for body text (SC 1.4.3) and 3:1 for the
 * boundaries and indicators a reader needs in order to identify a control or its state
 * (SC 1.4.11). The brief says 4.5 for everything. Where the brief and the standard
 * disagree the standard wins and the deviation gets a comment - a 4.5:1 hairline would
 * be a lit cage drawn around every card on the screen.
 */

import { AA_NON_TEXT, AA_TEXT, contrastRatio, reportRatio, type Hex } from './contrast.js';
import {
  DIVIDER,
  FOCUS_RING,
  INK,
  ON_FILL,
  ON_SIGNAL,
  PAPER,
  PENDING,
  SIGNAL,
  SURFACES,
  TEXT_ACCENT,
  VERIFY,
  type Surface,
} from './palette.js';
import { SEVERITY, SEVERITY_LEVELS } from './severity.js';

export type PairingKind = 'text' | 'non-text';

export interface Pairing {
  /** Human-readable, and it is what the CI failure prints. Make it say where it renders. */
  readonly name: string;
  readonly foreground: Hex;
  readonly background: Hex;
  readonly kind: PairingKind;
  readonly surface: Surface;
}

export interface PairingResult extends Pairing {
  readonly ratio: number;
  readonly floor: number;
  readonly passes: boolean;
}

export function floorFor(kind: PairingKind): number {
  return kind === 'text' ? AA_TEXT : AA_NON_TEXT;
}

/**
 * Pairings that sit below their floor on purpose.
 *
 * Each needs a reason that says what would break if it were raised. This list is short
 * and it is meant to stay short: it is the only way anything gets past the gate.
 */
export interface Exemption {
  readonly name: string;
  readonly reason: string;
}

export const EXEMPTIONS: readonly Exemption[] = [
  {
    name: 'divider on base (dark)',
    reason:
      'A hairline is decoration, not an indicator: SC 1.4.11 covers boundaries a reader ' +
      'needs in order to identify a control, and no control is identified by a table ' +
      'rule. At 3:1 it becomes a lit grid over every card on a dark console.',
  },
  {
    name: 'divider on base (light)',
    reason:
      'Same as the dark divider: it separates rows and it identifies nothing. On the ' +
      'light base a 3:1 rule also survives photocopying as a hard black line, and this ' +
      'dashboard is printed.',
  },
  {
    name: 'severity base marker on base (dark)',
    reason:
      'The raw ramp hue is a map marker and a card rule, never text and never a control ' +
      'boundary. It is always drawn with a shape and a text label beside it, both of ' +
      'which are gated above. Levels 0 and 4 are dark by design and cannot meet 3:1 on ' +
      '--ink-900 without ceasing to be the colours the brief specifies.',
  },
  {
    name: 'severity base marker on base (light)',
    reason:
      'Same as the dark marker, mirrored: levels 1 and 2 are light by design and cannot ' +
      'meet 3:1 on --paper-50 while remaining ochre and amber. The chip border beside ' +
      'them is gated and does meet it.',
  },
];

const EXEMPT_NAMES = new Set(EXEMPTIONS.map((exemption) => exemption.name));

export function isExempt(name: string): boolean {
  return EXEMPT_NAMES.has(name);
}

function text(name: string, fg: Hex, bg: Hex, surface: Surface): Pairing {
  return { name, foreground: fg, background: bg, kind: 'text', surface };
}

function nonText(name: string, fg: Hex, bg: Hex, surface: Surface): Pairing {
  return { name, foreground: fg, background: bg, kind: 'non-text', surface };
}

/** The severity ramp, swept exhaustively: 5 levels x 2 surfaces x 5 roles. */
function severityPairings(): Pairing[] {
  const pairings: Pairing[] = [];
  for (const level of SEVERITY_LEVELS) {
    const token = SEVERITY[level];
    for (const surface of ['dark', 'light'] as const) {
      const variant = token[surface];
      const base = SURFACES[surface].base;
      const raised = SURFACES[surface].raised;
      const card = SURFACES[surface].card;
      pairings.push(
        text(`sev-${level} label on its chip (${surface})`, variant.fg, variant.bg, surface),
        nonText(`sev-${level} chip border on base (${surface})`, variant.border, base, surface),
        nonText(`sev-${level} chip border on raised (${surface})`, variant.border, raised, surface),
        nonText(`sev-${level} chip border on card (${surface})`, variant.border, card, surface),
        // Declared so the raw hue is measured rather than unmeasured. It is in
        // EXEMPTIONS because it is a marker, and the reason is recorded there.
        nonText(`severity base marker on base (${surface})`, token.base, base, surface),
      );
    }
  }
  return pairings;
}

function interfacePairings(): Pairing[] {
  const dark = SURFACES.dark;
  const light = SURFACES.light;

  return [
    // --- dark base: the operations console ---
    text('primary text on base (dark)', dark.text, dark.base, 'dark'),
    text('primary text on raised (dark)', dark.text, dark.raised, 'dark'),
    text('primary text on card (dark)', dark.text, dark.card, 'dark'),
    text('secondary text on base (dark)', dark.muted, dark.base, 'dark'),
    text('secondary text on raised (dark)', dark.muted, dark.raised, 'dark'),
    text('secondary text on card (dark)', dark.muted, dark.card, 'dark'),
    text('accent text on base (dark)', TEXT_ACCENT.dark, dark.base, 'dark'),
    text('accent text on raised (dark)', TEXT_ACCENT.dark, dark.raised, 'dark'),
    text('accent text on card (dark)', TEXT_ACCENT.dark, dark.card, 'dark'),
    text('verified text on base (dark)', VERIFY[400], dark.base, 'dark'),
    text('verified text on card (dark)', VERIFY[400], dark.card, 'dark'),
    text('pending text on base (dark)', PENDING[400], dark.base, 'dark'),
    text('pending text on card (dark)', PENDING[400], dark.card, 'dark'),
    nonText('focus ring on base (dark)', FOCUS_RING.dark, dark.base, 'dark'),
    nonText('focus ring on raised (dark)', FOCUS_RING.dark, dark.raised, 'dark'),
    nonText('focus ring on card (dark)', FOCUS_RING.dark, dark.card, 'dark'),
    nonText('divider on base (dark)', DIVIDER.dark, dark.base, 'dark'),

    // --- light base: the public dashboard ---
    text('primary text on base (light)', light.text, light.base, 'light'),
    text('primary text on raised (light)', light.text, light.raised, 'light'),
    text('secondary text on base (light)', light.muted, light.base, 'light'),
    text('secondary text on raised (light)', light.muted, light.raised, 'light'),
    text('accent text on base (light)', TEXT_ACCENT.light, light.base, 'light'),
    text('accent text on raised (light)', TEXT_ACCENT.light, light.raised, 'light'),
    text('verified text on base (light)', VERIFY[500], light.base, 'light'),
    text('pending text on base (light)', PENDING[500], light.base, 'light'),
    nonText('focus ring on base (light)', FOCUS_RING.light, light.base, 'light'),
    nonText('focus ring on raised (light)', FOCUS_RING.light, light.raised, 'light'),
    nonText('divider on base (light)', DIVIDER.light, light.base, 'light'),

    // --- filled controls, measured in every state they can be in ---
    text('primary button label (rest)', ON_SIGNAL, SIGNAL[500], 'dark'),
    text('primary button label (hover)', ON_SIGNAL, SIGNAL[600], 'dark'),
    text('text on the signal tint', SIGNAL[700], SIGNAL[100], 'light'),
    text('verified badge label', ON_SIGNAL, VERIFY[500], 'light'),
    text('pending gate banner label', ON_SIGNAL, PENDING[500], 'light'),
    text('text on a severity fill', ON_FILL, SEVERITY[4].base, 'dark'),

    // A raised surface is deliberately NOT measured against the base it sits on. SC
    // 1.4.11 governs the boundaries that identify a control, and a card is identified by
    // its divider - which is measured - not by its fill. Holding a card's fill to 3:1
    // against the page would put a near-white panel on a dark console.
  ];
}

/** Every pairing the gate measures. */
export function allPairings(): readonly Pairing[] {
  return [...interfacePairings(), ...severityPairings()];
}

export function evaluate(pairing: Pairing): PairingResult {
  const floor = floorFor(pairing.kind);
  const ratio = reportRatio(contrastRatio(pairing.foreground, pairing.background));
  return { ...pairing, ratio, floor, passes: ratio >= floor };
}

export function evaluateAll(): readonly PairingResult[] {
  return allPairings().map(evaluate);
}

/** Results that fail their floor and are not exempt. These fail CI. */
export function failures(): readonly PairingResult[] {
  return evaluateAll().filter((result) => !result.passes && !isExempt(result.name));
}

/**
 * Every colour value the token layer defines, keyed by the name a developer would use.
 *
 * The exhaustiveness guard reads this. Anything added to the palette or the ramp has to
 * appear here, and `unpairedTokens()` then forces it into a pairing.
 */
export function allColourTokens(): Readonly<Record<string, Hex>> {
  const tokens: Record<string, Hex> = {
    'ink-900': INK[900],
    'ink-800': INK[800],
    'ink-700': INK[700],
    'ink-600': INK[600],
    'ink-300': INK[300],
    'ink-050': INK[50],
    'paper-50': PAPER[50],
    'paper-100': PAPER[100],
    'paper-900': PAPER[900],
    'signal-700': SIGNAL[700],
    'signal-600': SIGNAL[600],
    'signal-500': SIGNAL[500],
    'signal-400': SIGNAL[400],
    'signal-100': SIGNAL[100],
    'verify-500': VERIFY[500],
    'verify-400': VERIFY[400],
    'pending-500': PENDING[500],
    'pending-400': PENDING[400],
    'on-fill': ON_FILL,
    'on-signal': ON_SIGNAL,
    'divider-dark': DIVIDER.dark,
    'divider-light': DIVIDER.light,
    'muted-light': SURFACES.light.muted,
  };
  for (const level of SEVERITY_LEVELS) {
    const token = SEVERITY[level];
    tokens[`sev-${level}`] = token.base;
    for (const surface of ['dark', 'light'] as const) {
      tokens[`sev-${level}-${surface}-bg`] = token[surface].bg;
      tokens[`sev-${level}-${surface}-fg`] = token[surface].fg;
      tokens[`sev-${level}-${surface}-border`] = token[surface].border;
    }
  }
  return tokens;
}

/**
 * Token names that appear in no declared pairing.
 *
 * This is what makes "every token pairing is tested" a true statement rather than an
 * aspiration: a value can go unmeasured only by being absent from the palette entirely.
 */
export function unpairedTokens(): readonly string[] {
  const used = new Set<string>();
  for (const pairing of allPairings()) {
    used.add(pairing.foreground.toUpperCase());
    used.add(pairing.background.toUpperCase());
  }
  return Object.entries(allColourTokens())
    .filter(([, value]) => !used.has(value.toUpperCase()))
    .map(([name]) => name)
    .sort();
}
