/**
 * The paper tier: a printed form, a QR code, and the record that survives both.
 *
 * The lowest offline tier that actually exists in the field. A dead phone in week three of
 * a recovery is not an edge case — it is a Tuesday — and an officer who has to stop working
 * is a data gap that never gets filled, because nobody goes back to re-survey a division
 * that was already done.
 *
 * So: the ops console prints trilingual assessment forms, each carrying a QR code with the
 * household reference, the division and the form version. The officer fills the paper. Days
 * later, with a charged phone, they scan the QR, the digital form pre-fills the fields the
 * code carries, they complete the rest, and they photograph the paper as evidence.
 *
 * **What the QR carries, and what it deliberately does not.** It carries a household
 * *reference code*, a division code and a version. It does not carry a name, a phone
 * number, a household id or a coordinate. A printed form is left on kitchen tables, dropped
 * in the street and photographed by anyone; a QR code that resolved to a household's
 * identity would be a register leak with legs. The reference is meaningless without the
 * register, and the register is on the officer's encrypted device.
 *
 * The resulting record carries `source: PAPER` and the photograph of the form, so an
 * auditor six months later can see that this assessment went through the paper stage and
 * can look at the paper.
 */

/**
 * The payload version. Bumped when the field set changes.
 *
 * Forms print with a version because a stack of them sits in a drawer for months. A scanner
 * that met a version it did not know and guessed would pre-fill the wrong fields into a
 * form the officer then signs off.
 */
export const PAPER_FORM_VERSION = 1;

/** `SARANA:AF:` — Sarana, Assessment Form. Short, because QR density costs scan reliability. */
const PREFIX = 'SARANA:AF:';

export interface PaperFormPayload {
  readonly version: number;
  readonly householdReference: string;
  readonly gnDivisionCode: string;
  /** The hazard event the form was printed for. Optional: blank forms exist. */
  readonly hazardEventId?: string | null;
}

export class PaperFormUnreadable extends Error {
  constructor(
    message: string,
    /** What the scanner actually saw, for the screen to show. Never logged. */
    readonly scanned: string,
  ) {
    super(message);
    this.name = 'PaperFormUnreadable';
  }
}

/**
 * Encode a payload for printing.
 *
 * Pipe-delimited rather than JSON: a QR code's error correction degrades with density, and
 * these are printed on a laser printer, folded into a pocket, rained on and then scanned in
 * poor light. Every byte removed is a scan that works.
 */
export function encodePaperForm(payload: PaperFormPayload): string {
  for (const [field, value] of [
    ['householdReference', payload.householdReference],
    ['gnDivisionCode', payload.gnDivisionCode],
  ] as const) {
    if (!value || value.includes('|')) {
      throw new Error(`${field} is empty or contains the delimiter, so it cannot be encoded`);
    }
  }

  return [
    `${PREFIX}${payload.version}`,
    payload.householdReference,
    payload.gnDivisionCode,
    payload.hazardEventId ?? '',
  ].join('|');
}

/**
 * Read a scanned code.
 *
 * Refuses rather than guesses, on every branch. A QR from another system, a damaged scan or
 * a newer form version all produce a named refusal the screen can show — because the
 * alternative is pre-filling a household reference that belongs to somebody else into a
 * form the officer is about to attest to.
 */
export function decodePaperForm(scanned: string): PaperFormPayload {
  const raw = scanned.trim();

  if (!raw.startsWith(PREFIX)) {
    throw new PaperFormUnreadable(
      'That is not a SARANA assessment form. Scan the code printed on the form itself.',
      raw,
    );
  }

  const parts = raw.split('|');
  if (parts.length !== 4) {
    throw new PaperFormUnreadable(
      'The code did not scan completely. Flatten the form and try again in better light.',
      raw,
    );
  }

  const version = Number.parseInt(parts[0]!.slice(PREFIX.length), 10);
  if (!Number.isInteger(version)) {
    throw new PaperFormUnreadable('The code did not scan completely.', raw);
  }
  if (version > PAPER_FORM_VERSION) {
    throw new PaperFormUnreadable(
      `This form is version ${version} and this app reads up to ${PAPER_FORM_VERSION}. ` +
        'Update the app before transcribing it, or the wrong fields will be filled in.',
      raw,
    );
  }

  const [, householdReference, gnDivisionCode, hazardEventId] = parts;
  if (!householdReference || !gnDivisionCode) {
    throw new PaperFormUnreadable(
      'The code is missing the household reference or the division.',
      raw,
    );
  }

  return {
    version,
    householdReference,
    gnDivisionCode,
    hazardEventId: hazardEventId && hazardEventId.length > 0 ? hazardEventId : null,
  };
}

/**
 * Whether a scanned form may be transcribed by an officer permitted in `division`.
 *
 * Checked before the form opens, not on sync. An officer who transcribes twenty forms from
 * a neighbouring division has done twenty pieces of work the server will refuse, and will
 * find out three days later.
 */
export function mayTranscribe(
  payload: PaperFormPayload,
  division: string,
): { readonly allowed: boolean; readonly reason?: string } {
  if (payload.gnDivisionCode !== division) {
    return {
      allowed: false,
      reason:
        `This form is for ${payload.gnDivisionCode} and your offline permit covers ` +
        `${division}. It would be refused when it syncs.`,
    };
  }
  return { allowed: true };
}

/**
 * Where an assessment record came from.
 *
 * `PHONE` is the default and `PAPER` marks a transcription. It is on the record rather than
 * inferred from the presence of a form photograph, because the two can come apart: a form
 * photographed but not transcribed, or transcribed from a form that was too wet to
 * photograph. An auditor asking "did this go through paper?" needs an answer, not a guess.
 */
export const ASSESSMENT_SOURCES = ['PHONE', 'PAPER'] as const;
export type AssessmentSource = (typeof ASSESSMENT_SOURCES)[number];
