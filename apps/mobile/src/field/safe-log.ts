/**
 * The only logger the Field Companion uses, and what it refuses to write.
 *
 * The brief's rule: "Names and contact numbers are stored **encrypted**, decrypted only for
 * display, never written to logs." That is easy to state and easy to break — one
 * `console.log(household)` while debugging a search bug, committed by accident, and every
 * name in the division is in logcat, which on Android is readable by a connected computer
 * and is what a crash reporter uploads.
 *
 * **The defence is that there is nothing to log.** `redact` takes any value and returns one
 * with the personal fields replaced before it reaches a transport. It is not a filter over
 * strings after the fact — that would be a blocklist, and a blocklist over free text always
 * loses. It is a whitelist over structure: a field named in `SENSITIVE_KEYS` is replaced
 * whatever it contains, and a decrypted `Household` has no path through this module that
 * keeps its name.
 *
 * `test/log-pii-sweep.test.ts` drives real flows through a capturing sink and asserts the
 * seeded names and numbers appear nowhere in what was written. That is the gate; this is
 * the mechanism.
 */

/**
 * Field names that never reach a log, whatever they hold.
 *
 * A whitelist over structure rather than a blocklist over text. `name` is here even though
 * plenty of harmless things are called `name` — a redacted division name costs nothing, and
 * the alternative is deciding case by case which `name` is a person, which is a decision
 * somebody eventually gets wrong at 2am.
 */
export const SENSITIVE_KEYS: readonly string[] = [
  'name',
  'names',
  'full_name',
  'fullName',
  'household_name',
  'householdName',
  'contact',
  'contact_number',
  'contactNumber',
  'phone',
  'phone_number',
  'phoneNumber',
  'msisdn',
  'nic',
  'nic_number',
  'nicNumber',
  'email',
  'address',
  'name_cipher',
  'nameCipher',
  'contact_cipher',
  'contactCipher',
  // The search index is a keyed hash of the name tokens. It is not plaintext, and it is
  // still a stable per-name identifier that correlates a household across log lines.
  'name_search',
  'nameSearch',
];

/** What a redacted field is replaced with. Recognisable in a log, and not a value. */
export const REDACTED = '[redacted]';

/**
 * Depth limit for the walk.
 *
 * A malformed or circular structure must not hang the logger. Eight is deeper than any
 * shape this app logs; past it the value is replaced rather than truncated, because a
 * half-walked object may be half-redacted.
 */
const MAX_DEPTH = 8;

function isSensitive(key: string): boolean {
  const lowered = key.toLowerCase();
  return SENSITIVE_KEYS.some((sensitive) => sensitive.toLowerCase() === lowered);
}

/**
 * Replace every sensitive field in a value, however deeply nested.
 *
 * Returns a new value; the input is never mutated. A logger that redacted in place would
 * blank the object the caller is about to render to the screen, which is the one place the
 * name is supposed to appear.
 */
export function redact(value: unknown, depth = 0): unknown {
  if (depth > MAX_DEPTH) return REDACTED;
  if (value === null || value === undefined) return value;

  if (Array.isArray(value)) return value.map((entry) => redact(entry, depth + 1));

  if (value instanceof Error) {
    // The message and the name, never the stack: a stack from a bundled React Native build
    // is noise, and an error thrown while formatting a household can carry the household
    // into its own message.
    return { error: value.name, message: redactText(value.message) };
  }

  if (typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      out[key] = isSensitive(key) ? REDACTED : redact(entry, depth + 1);
    }
    return out;
  }

  if (typeof value === 'string') return redactText(value);

  return value;
}

/**
 * A Sri Lankan mobile number or NIC appearing inside free text.
 *
 * The one place a blocklist is used, and it is a backstop rather than the defence. A
 * structured field is redacted by its key; this catches a number that has been interpolated
 * into a message — `"failed to reach +94771234567"` — where there is no key to match on.
 *
 * Patterns match `gov_mock.data.names`, the same generators the public dashboard's PII
 * sweep is built from, so the two surfaces refuse the same shapes.
 */
const NUMBER_PATTERNS: readonly RegExp[] = [
  // +94 7X ....... and the local 07X ....... form.
  /(?<![\w+])(?:\+94|0)7[0-8]\d{7}(?![\d])/g,
  // NIC, both formats in circulation. Bounded by non-hex so a digest is not mangled.
  /(?<![0-9a-fA-F])\d{12}(?![0-9a-fA-F])/g,
  /(?<![0-9a-zA-Z])\d{9}[VXvx](?![0-9a-zA-Z])/g,
];

export function redactText(text: string): string {
  let out = text;
  for (const pattern of NUMBER_PATTERNS) {
    out = out.replace(new RegExp(pattern.source, pattern.flags), REDACTED);
  }
  return out;
}

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

/** Where a log line goes. `console` on a handset; a capturing array in the sweep test. */
export interface LogSink {
  write(level: LogLevel, message: string, context: unknown): void;
}

export const consoleSink: LogSink = {
  write(level, message, context) {
    // `warn` and `error` only in production builds. A debug line on a field device costs
    // battery writing to a log nobody reads, and is one more place a value can end up.
    const target = level === 'error' ? console.error : console.warn;
    target(`[sarana] ${message}`, context);
  },
};

/**
 * The Field Companion's logger.
 *
 * Every call redacts before it writes, so a caller cannot forget. The message itself is
 * redacted too: interpolating a household name into a message string is the mistake that
 * a context-only redaction would miss entirely.
 */
export class SafeLog {
  constructor(private readonly sink: LogSink = consoleSink) {}

  debug(message: string, context: unknown = {}): void {
    this.sink.write('debug', redactText(message), redact(context));
  }

  info(message: string, context: unknown = {}): void {
    this.sink.write('info', redactText(message), redact(context));
  }

  warn(message: string, context: unknown = {}): void {
    this.sink.write('warn', redactText(message), redact(context));
  }

  error(message: string, context: unknown = {}): void {
    this.sink.write('error', redactText(message), redact(context));
  }
}

/** The app's logger. One instance, so a test can swap the sink under everything. */
export const fieldLog = new SafeLog();
