/**
 * The token layer's guarantees, held as tests rather than as intentions.
 *
 * These are the rules the design system is defensible by. Each one breaks something
 * concrete if it stops holding, and the docstrings say what.
 */

import { describe, expect, it } from 'vitest';

import { AA_NON_TEXT, AA_TEXT, contrastRatio, InvalidHexError, reportRatio } from './contrast.js';
import { INK, PAPER, PENDING, SIGNAL, SURFACES, TEXT_ACCENT, VERIFY } from './palette.js';
import { EXEMPTIONS, evaluateAll, failures, isExempt, unpairedTokens } from './pairings.js';
import { SEVERITY, SEVERITY_LABELS, SEVERITY_LEVELS } from './severity.js';
import {
  MIN_MOBILE_SIZE,
  SCRIPT_METRICS,
  TYPE_SCALE,
  lineHeightFor,
  sizeFor,
  type TypeSize,
} from './typography.js';
import { SPACE, SPACE_BASE, TOUCH_TARGET_MIN, TOUCH_TARGET_SOS } from './layout.js';

const SIZES = Object.keys(TYPE_SCALE) as TypeSize[];

describe('contrast maths', () => {
  it('gives 21:1 for black on white, the definitional maximum', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 5);
  });

  it('gives 1:1 for a colour against itself', () => {
    expect(contrastRatio('#0E7C86', '#0E7C86')).toBeCloseTo(1, 10);
  });

  it('returns the same ratio whichever way round the pair is written', () => {
    // A pairing table that answered differently for (fg, bg) than for (bg, fg) would let
    // a failing pair pass by being written the other way round.
    expect(contrastRatio(INK[50], INK[900])).toBeCloseTo(contrastRatio(INK[900], INK[50]), 10);
  });

  it('rounds a reported ratio down, so a near miss fails instead of being rounded up', () => {
    expect(reportRatio(4.4999)).toBe(4.49);
    expect(reportRatio(4.5001)).toBe(4.5);
  });

  it('refuses anything that is not a six-digit sRGB hex', () => {
    expect(() => contrastRatio('#FFF', '#000000')).toThrow(InvalidHexError);
    expect(() => contrastRatio('rgb(0,0,0)', '#000000')).toThrow(InvalidHexError);
  });
});

describe('the contrast gate', () => {
  it('passes every declared pairing that is not exempt', () => {
    // If this fails, the failure message names the pairing and both hexes. Fix the
    // colour or add an exemption with a reason; do not lower the floor.
    expect(failures().map((f) => `${f.name}: ${f.ratio}:1 needs ${f.floor}:1`)).toEqual([]);
  });

  it('measures every colour token in at least one pairing', () => {
    // This is what makes "every token pairing is tested" true rather than aspirational.
    // A new token can escape the gate only by not existing.
    expect(unpairedTokens()).toEqual([]);
  });

  it('holds body text to 4.5:1 and control boundaries to 3:1, and nothing to less', () => {
    for (const result of evaluateAll()) {
      expect(result.floor).toBe(result.kind === 'text' ? AA_TEXT : AA_NON_TEXT);
    }
  });

  it('gives every exemption a reason long enough to be an argument', () => {
    // An exemption with "legacy" written next to it is how an accessibility floor
    // erodes. Each one has to say what breaks if the pairing were raised.
    for (const exemption of EXEMPTIONS) {
      expect(exemption.reason.length).toBeGreaterThan(60);
    }
  });

  it('exempts nothing that is not actually below its floor', () => {
    // A stale exemption is worse than none: it reads as a known problem that is not one,
    // and it hides the next real one.
    const belowFloor = new Set(evaluateAll().filter((r) => !r.passes).map((r) => r.name));
    for (const exemption of EXEMPTIONS) {
      expect(belowFloor.has(exemption.name), `${exemption.name} now passes`).toBe(true);
    }
  });

  it('exempts no text pairing', () => {
    // Every exemption in this system is a border or a marker. If a *text* pairing ever
    // needs one, that is a design failure, not a documentation exercise.
    for (const result of evaluateAll()) {
      if (isExempt(result.name)) expect(result.kind).toBe('non-text');
    }
  });
});

describe('the severity ramp', () => {
  it('keeps the five base hexes the brief specified', () => {
    // These are the colours operators already read under stress. Changing one is a
    // decision about a standard they know, not a palette tweak.
    expect(SEVERITY_LEVELS.map((level) => SEVERITY[level].base)).toEqual([
      '#4A5568',
      '#C9A227',
      '#D97706',
      '#DC2626',
      '#7F1D1D',
    ]);
  });

  it('gives every level a distinct shape, so severity never depends on colour', () => {
    // Roughly 8% of men have a colour vision deficiency. A ramp that is discriminable
    // only by hue is unreadable to one operator in twelve at the moment it matters.
    const shapes = SEVERITY_LEVELS.map((level) => SEVERITY[level].shape);
    expect(new Set(shapes).size).toBe(SEVERITY_LEVELS.length);
  });

  it('gives every level a label in all three languages', () => {
    for (const level of SEVERITY_LEVELS) {
      const label = SEVERITY_LABELS[level];
      for (const locale of ['si', 'ta', 'en'] as const) {
        expect(label[locale].trim().length, `sev-${level}.${locale}`).toBeGreaterThan(0);
      }
    }
  });

  it('separates the level-4 label from every tint label by luminance alone', () => {
    // The claim the fill exists to make, and it lives in the label rather than in the
    // fill. On the dark base every chip background is dark, level 4 included - the fills
    // sit within 1.32:1 of each other - so what actually inverts is the text: level 4
    // reads near-white while every tint reads mid-toned. That is the difference a reader
    // catches with no colour vision and without resolving the shape, which is what
    // "evacuate" has to be.
    for (const surface of ['dark', 'light'] as const) {
      for (const level of [0, 1, 2, 3] as const) {
        expect(
          contrastRatio(SEVERITY[4][surface].fg, SEVERITY[level][surface].fg),
          `sev-4 label vs sev-${level} label (${surface})`,
        ).toBeGreaterThan(2);
      }
    }
  });

  it('does not separate the tints by luminance, which is why shape and label are mandatory', () => {
    // Measured, not assumed. Ochre, amber and red at one tint lightness land within
    // 1.06:1 of each other in greyscale: a reader with a colour vision deficiency cannot
    // tell an advisory chip from a watch chip by its fill at all. Separating them would
    // mean abandoning either the brief's five hues or a uniform tint lightness, and the
    // system chooses instead to carry the meaning in a shape and a word.
    //
    // This test is here so that anyone who proposes dropping the shape or the label from
    // SeverityPill sees the number first - and so that if the ramp is ever re-tuned to be
    // luminance-separated, it fails and says the shape rule can be relaxed.
    const separations: number[] = [];
    for (const surface of ['dark', 'light'] as const) {
      for (const level of [0, 1, 2] as const) {
        const next = (level + 1) as 1 | 2 | 3;
        separations.push(
          contrastRatio(SEVERITY[level][surface].bg, SEVERITY[next][surface].bg),
        );
      }
    }
    expect(Math.min(...separations)).toBeLessThan(1.2);
  });

  it('renders level 4 as a fill on both surfaces', () => {
    // The one level that inverts. It is what makes "evacuate" discriminable across a
    // room, without colour and without reading the shape.
    expect(SEVERITY[4].dark.bg).toBe(SEVERITY[4].base);
    expect(SEVERITY[4].light.bg).toBe(SEVERITY[4].base);
  });
});

describe('the interface palette', () => {
  it('keeps every interface accent cool, so nothing can be read as a severity signal', () => {
    // The single rule the whole palette exists to serve. A warm interface accent would
    // put an orange element on screen that is not a watch-level hazard, and after that
    // an operator has to check every coloured thing instead of trusting the ramp.
    const accents = [
      ...Object.values(SIGNAL),
      ...Object.values(VERIFY),
      ...Object.values(PENDING),
      TEXT_ACCENT.dark,
      TEXT_ACCENT.light,
    ];
    for (const hex of accents) {
      const [r, , b] = [
        Number.parseInt(hex.slice(1, 3), 16),
        Number.parseInt(hex.slice(3, 5), 16),
        Number.parseInt(hex.slice(5, 7), 16),
      ];
      // Cool means blue is not the weakest channel. Every warm hue in the severity ramp
      // fails this; every interface accent passes it.
      expect(b, `${hex} has more red than blue and would read as a hazard`).toBeGreaterThan(r!);
    }
  });

  it('keeps the two base surfaces the brief specified', () => {
    expect(SURFACES.dark.base).toBe(INK[900]);
    expect(SURFACES.light.base).toBe(PAPER[50]);
  });

  it('darkens the primary button on hover rather than lightening it', () => {
    // The brief names --signal-400 as the hover. White on it is 3.16:1, and a hover
    // state is not exempt from SC 1.4.3 - the label would drop below AA at the moment
    // the pointer was on it.
    expect(contrastRatio('#FFFFFF', SIGNAL[600])).toBeGreaterThanOrEqual(AA_TEXT);
    expect(contrastRatio('#FFFFFF', SIGNAL[400])).toBeLessThan(AA_TEXT);
  });
});

describe('the three-script type scale', () => {
  it('uses the eight steps the brief specified', () => {
    expect(Object.values(TYPE_SCALE)).toEqual([12, 13, 14, 16, 20, 26, 34, 44]);
  });

  it('never renders below 13px in Sinhala or Tamil either', () => {
    // A GN officer is reading this in rain with wet hands. 12px is desktop chrome only,
    // and the per-script uplift must not round a size back under the floor.
    for (const locale of ['si', 'ta', 'en'] as const) {
      for (const size of SIZES) {
        if (TYPE_SCALE[size] < MIN_MOBILE_SIZE) continue;
        expect(sizeFor(size, locale), `${size} in ${locale}`).toBeGreaterThanOrEqual(
          MIN_MOBILE_SIZE,
        );
      }
    }
  });

  it('gives Sinhala and Tamil more leading than Latin at every step', () => {
    // Sinhala's ascender/descender range is the widest of the three; at Latin leading
    // the ේ of one line touches the ු of the line above.
    for (const size of SIZES) {
      expect(lineHeightFor(size, 'si'), size).toBeGreaterThan(lineHeightFor(size, 'en'));
      expect(lineHeightFor(size, 'ta'), size).toBeGreaterThan(lineHeightFor(size, 'en'));
    }
  });

  it('gives Sinhala more leading than Tamil, which is shallower vertically', () => {
    for (const size of SIZES) {
      expect(lineHeightFor(size, 'si'), size).toBeGreaterThan(lineHeightFor(size, 'ta'));
    }
  });

  it('stops the size uplift above body size', () => {
    // Scaling a 44px headline by 1.06 pushes a three-word Tamil title onto a second
    // line, and the scripts already match optically at display sizes.
    for (const locale of ['si', 'ta'] as const) {
      expect(sizeFor('base', locale)).toBeGreaterThan(TYPE_SCALE.base);
      expect(sizeFor('2xl', locale)).toBe(TYPE_SCALE['2xl']);
      expect(sizeFor('3xl', locale)).toBe(TYPE_SCALE['3xl']);
    }
  });

  it('renders every size as a whole pixel', () => {
    // A fractional font-size renders differently across the three engines this has to
    // look identical in.
    for (const locale of ['si', 'ta', 'en'] as const) {
      for (const size of SIZES) {
        expect(Number.isInteger(sizeFor(size, locale)), `${size} in ${locale}`).toBe(true);
      }
    }
  });

  it('puts the right Noto face first in each script stack', () => {
    expect(SCRIPT_METRICS.si.stack).toMatch(/^'Noto Sans Sinhala'/);
    expect(SCRIPT_METRICS.ta.stack).toMatch(/^'Noto Sans Tamil'/);
  });
});

describe('spacing and targets', () => {
  it('keeps every spacing step a multiple of the 4px base', () => {
    for (const [step, value] of Object.entries(SPACE)) {
      expect(value % SPACE_BASE, `space-${step}`).toBe(0);
    }
  });

  it('meets the WCAG 2.2 target-size floor, and exceeds it for the SOS button', () => {
    // The SOS button is pressed one-handed, in the dark, by someone frightened. The
    // extra 12px is the difference between a deliberate press and a missed one.
    expect(TOUCH_TARGET_MIN).toBeGreaterThanOrEqual(44);
    expect(TOUCH_TARGET_SOS).toBeGreaterThan(TOUCH_TARGET_MIN);
  });
});
