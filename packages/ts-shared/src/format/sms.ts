/**
 * How many SMS segments a message costs.
 *
 * A deliberate mirror of `sarana_shared.domain.sms`, and the only duplicated logic in the
 * repository. It exists because the alert composer has to show the segment count for all
 * three languages **while the operator is typing**, before any draft exists to ask the
 * server about — and a preview that only appeared after drafting would tell an author
 * their Tamil message is three segments at the point it is too late to reword it.
 *
 * The constants below are the same constants, and `sms.test.ts` pins them against the
 * values in the Python module. If the two ever disagree, the Python one is right: it is
 * what the gateway adapter actually counts with, and this is a preview.
 *
 * ## Why this is a life-safety concern and not a billing detail
 *
 * A GSM message is transmitted by segments, and which alphabet the text falls into decides
 * how many characters fit in one. GSM-7 gets 160 in a single segment; UCS-2 — which is
 * every Sinhala and Tamil message this platform will ever send — gets 70.
 *
 * So an English warning that fits comfortably in one segment becomes three in Sinhala.
 * During a national fan-out that is three times the cost, three times the gateway queue,
 * and three separate parts that can arrive out of order or not at all on a congested
 * network. The community reading the Tamil version is the one whose warning arrives last
 * and truncated — the exact Ditwah failure this platform exists to correct, reproduced
 * through a billing detail.
 */

/**
 * GSM 03.38 basic character set.
 *
 * A character outside this and the extension table forces the whole message to UCS-2, so
 * one Sinhala letter in an otherwise English message costs the same as a wholly Sinhala
 * one. Mixed-script templates are a trap for exactly this reason.
 */
const GSM7_BASIC = new Set(
  '@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?' +
    '¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§' +
    '¿abcdefghijklmnopqrstuvwxyzäöñüà',
);

/** Each of these is an escape plus the character, so it costs two septets rather than one. */
const GSM7_EXTENDED = new Set('^{}\\[~]|€');

export const GSM7_SINGLE = 160;
export const GSM7_CONCATENATED = 153;
export const UCS2_SINGLE = 70;
export const UCS2_CONCATENATED = 67;

/**
 * The ceiling a citizen-facing template must fit inside, in every language.
 *
 * Two rather than one, because a useful evacuation instruction naming a division and a
 * shelter does not fit in 70 UCS-2 characters, and writing to that limit would strip the
 * place names that make the message actionable. Two rather than three, because each extra
 * part is another chance for the message to arrive incomplete on a network that is already
 * the reason people are being warned by SMS.
 */
export const MAX_SEGMENTS = 2;

export type SmsEncoding = 'GSM7' | 'UCS2';

/**
 * Which alphabet this text needs.
 *
 * One character outside GSM-7 moves the entire message. There is no partial encoding: the
 * alphabet is a property of the message, not of its characters.
 */
export function encodingFor(text: string): SmsEncoding {
  // Iterating the string yields code points, so an astral character is tested once rather
  // than as two lone surrogates — both of which would be outside GSM-7 anyway, but the
  // intent matters if the sets ever grow.
  for (const character of text) {
    if (!GSM7_BASIC.has(character) && !GSM7_EXTENDED.has(character)) return 'UCS2';
  }
  return 'GSM7';
}

/**
 * The transmitted length, in the units its alphabet is measured in.
 *
 * For GSM-7 that is septets, with extension-table characters counting twice. For UCS-2 it
 * is UTF-16 code units — which is what `String.prototype.length` already returns in
 * JavaScript, and it is the right number: a character outside the Basic Multilingual Plane
 * occupies two units, and counting code points would under-count and let a message through
 * that the gateway then splits into one more part than was budgeted for.
 */
export function unitsIn(text: string): number {
  if (encodingFor(text) === 'UCS2') return text.length;

  let units = 0;
  for (const character of text) {
    units += GSM7_EXTENDED.has(character) ? 2 : 1;
  }
  return units;
}

export interface SegmentCount {
  readonly textLength: number;
  readonly encoding: SmsEncoding;
  readonly units: number;
  readonly segments: number;
  readonly limitAtMax: number;
  readonly withinLimit: boolean;
  /**
   * Units still available before the message needs another segment. Negative when over.
   *
   * Reported rather than a bare pass/fail because a template sitting one character under
   * the limit is one an operator will break with the next place name, and the author
   * should see that while they are still writing.
   */
  readonly headroom: number;
}

/**
 * How many segments this message takes, and how much room is left.
 *
 * An empty message is one segment, not zero: a gateway asked to send nothing still sends
 * something, and reporting zero would let an empty template pass a length check that
 * exists to catch exactly the templates nobody looked at.
 */
export function countSegments(text: string, maxSegments: number = MAX_SEGMENTS): SegmentCount {
  const encoding = encodingFor(text);
  const units = unitsIn(text);

  const single = encoding === 'GSM7' ? GSM7_SINGLE : UCS2_SINGLE;
  const concatenated = encoding === 'GSM7' ? GSM7_CONCATENATED : UCS2_CONCATENATED;

  // Ceiling division: a message one unit over a boundary costs a whole extra segment.
  const segments = units <= single ? 1 : Math.ceil(units / concatenated);
  const limitAtMax = maxSegments === 1 ? single : concatenated * maxSegments;

  return {
    textLength: text.length,
    encoding,
    units,
    segments,
    limitAtMax,
    withinLimit: segments <= maxSegments,
    headroom: limitAtMax - units,
  };
}

/** Whether this message ships. The one-line form, for a call site that only branches. */
export function fitsInSegments(text: string, maxSegments: number = MAX_SEGMENTS): boolean {
  return countSegments(text, maxSegments).segments <= maxSegments;
}
