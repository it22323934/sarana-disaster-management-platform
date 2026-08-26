// LKR formatting for the frontend — mirrors packages/py-shared/sarana_shared/domain/money.py.
// The backend is the source of truth for LKRCents math; this module only renders what the
// API already returned, it never does money arithmetic client-side.

/** Minor units (1 LKRCents = LKR 0.01), matching the API's LKRCents type exactly. */
export type LKRCents = number;

/**
 * Rs. X,XXX.XX — the one money format used everywhere in the UI regardless of locale.
 * docs/build-prompts/20-ops-console.md: "a mixed-language operations room needs one
 * unambiguous money format" — this is intentionally NOT locale-sensitive.
 */
export function formatLkr(cents: LKRCents): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(Math.trunc(cents));
  const whole = Math.floor(abs / 100);
  const frac = abs % 100;
  const wholeFormatted = whole.toLocaleString("en-US");
  return `${sign}Rs. ${wholeFormatted}.${frac.toString().padStart(2, "0")}`;
}
