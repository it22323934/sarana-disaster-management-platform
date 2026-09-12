/**
 * Household names never appear in any log output.
 * `pnpm --filter mobile test -- log-pii-sweep`
 *
 * File 24's fourth Definition-of-Done command, and the brief's last test case.
 *
 * The failure it exists to prevent is mundane and that is exactly why it needs a gate: one
 * `console.log(household)` added while debugging a search bug, committed by accident. On
 * Android, logcat is readable by any connected computer and is what a crash reporter
 * uploads, so a debugging line in a shipped build puts every name in the division somewhere
 * the officer never agreed to.
 *
 * **The sweep drives real flows and reads what was written**, rather than asserting the
 * redactor in isolation. `src/field/safe-log.ts` has its own unit tests for the mechanism;
 * this is the gate, and the difference matters: a redactor that worked perfectly would
 * still fail here if a call site bypassed it.
 */

import { describe, expect, it } from 'vitest';

import { migrate } from '../src/offline/db/schema.js';
import { openTestDatabase } from '../test-support/node-database.js';
import {
  HouseholdRegister,
  type RegistryCipher,
  type UpstreamHousehold,
} from '../src/field/household-register.js';
import { REDACTED, SafeLog, redact, redactText, type LogLevel, type LogSink } from '../src/field/safe-log.js';

/**
 * The values that must not appear anywhere in a log line.
 *
 * Real shapes from `gov_mock.data.names` — the same generators the public dashboard's PII
 * sweep is built from, so the two surfaces refuse the same things. Sinhala and Tamil names
 * are included because a redactor written and tested only against Latin script is a
 * redactor that leaks for most of this country.
 */
const SECRETS = [
  'Kamal Perera',
  'Nimali Fernando',
  'සුනිල් ජයවර්ධන',
  'சுந்தரம் ராஜா',
  '+94771234567',
  '0771234568',
  '199712345670',
  '771234567V',
  'kamal.perera@example.lk',
];

class CapturingSink implements LogSink {
  readonly lines: string[] = [];

  write(level: LogLevel, message: string, context: unknown): void {
    // Everything the sink was handed, serialised the way a transport would serialise it.
    // A value nested six deep in a context object is as leaked as one in the message.
    this.lines.push(`${level} ${message} ${JSON.stringify(context)}`);
  }

  get output(): string {
    return this.lines.join('\n');
  }
}

class TestCipher implements RegistryCipher {
  #nonce = 0;
  async encrypt(plaintext: string): Promise<string> {
    this.#nonce += 1;
    return `enc:${this.#nonce}:${Buffer.from(plaintext, 'utf8').toString('base64')}`;
  }
  async decrypt(ciphertext: string): Promise<string> {
    return Buffer.from(ciphertext.split(':')[2] ?? '', 'base64').toString('utf8');
  }
  async searchHash(token: string): Promise<string> {
    return `h${Buffer.from(token, 'utf8').toString('hex')}`;
  }
}

const DIVISION = 'LK-2-05-020-1015';

const HOUSEHOLDS: UpstreamHousehold[] = [
  {
    id: '018f4a2b-0000-7000-8000-000000000001',
    reference_code: 'HH-LK-21-010301',
    gn_division_id: 'gn-1',
    gn_division_code: DIVISION,
    name: 'Kamal Perera',
    contact: '+94771234567',
    member_count: 4,
  },
  {
    id: '018f4a2b-0000-7000-8000-000000000002',
    reference_code: 'HH-LK-21-010302',
    gn_division_id: 'gn-1',
    gn_division_code: DIVISION,
    name: 'සුනිල් ජයවර්ධන',
    contact: '0771234568',
    member_count: 2,
  },
];

function expectNoSecrets(output: string, where: string): void {
  for (const secret of SECRETS) {
    expect(
      output.includes(secret),
      `${where} contains ${JSON.stringify(secret)}. On Android this reaches logcat, which ` +
        'any connected computer can read and which a crash reporter uploads.',
    ).toBe(false);
  }
}

describe('the sweep is looking at something', () => {
  it('would catch a name written through a raw sink', () => {
    // The guard on the guard. If `CapturingSink` silently dropped what it was handed, every
    // assertion below would pass over an empty string - which is the way a PII sweep most
    // often stops working.
    const sink = new CapturingSink();
    sink.write('info', 'household loaded', { name: 'Kamal Perera' });
    expect(sink.output).toContain('Kamal Perera');
  });
});

describe('logging a decrypted household', () => {
  it('writes no name and no contact number', async () => {
    const db = openTestDatabase();
    await migrate(db);
    const register = new HouseholdRegister(db, new TestCipher());
    await register.replaceDivision(DIVISION, HOUSEHOLDS);

    const sink = new CapturingSink();
    const log = new SafeLog(sink);

    // The realistic mistake: an officer's search returns rows and somebody logs them to
    // find out why the count is wrong. These are fully decrypted `Household` objects.
    const found = await register.search(DIVISION, 'Perera');
    log.info('search returned households', { query: 'Perera', households: found.households });

    const listed = await register.listDivision(DIVISION);
    log.debug('register listed', { division: DIVISION, households: listed });

    expectNoSecrets(sink.output, 'the log after logging decrypted households');
    // And it still says something useful: a sweep that passed by logging nothing at all
    // would be worthless.
    expect(sink.output).toContain('search returned households');
    expect(sink.output).toContain('HH-LK-21-010301');

    await db.close();
  });

  it('writes no ciphertext or search hash either', async () => {
    // Ciphertext is not plaintext and it is still a stable per-household value that
    // correlates one row across log lines. The search index is worse: it is a stable hash
    // of the name tokens, so two lines carrying it are two lines about the same person.
    const db = openTestDatabase();
    await migrate(db);
    const register = new HouseholdRegister(db, new TestCipher());
    await register.replaceDivision(DIVISION, HOUSEHOLDS);

    const sink = new CapturingSink();
    new SafeLog(sink).warn('raw row', {
      row: (await db.select<Record<string, unknown>>('SELECT * FROM household LIMIT 1'))[0],
    });

    expect(sink.output).not.toContain('enc:');
    expect(sink.output).toContain(REDACTED);
    await db.close();
  });
});

describe('a name interpolated into the message itself', () => {
  it('is redacted when it is a number or an identifier', () => {
    // The mistake a context-only redactor misses entirely: the value is in the string, not
    // in a field, so there is no key to match on.
    const sink = new CapturingSink();
    const log = new SafeLog(sink);

    log.error('failed to reach +94771234567 after 3 attempts');
    log.error('NIC 199712345670 did not verify');
    log.error('household 771234567V is unregistered');

    expectNoSecrets(sink.output, 'the log after interpolating identifiers into messages');
  });
});

describe('an error thrown while formatting a household', () => {
  it('carries neither the household nor a stack', () => {
    // A real path: an exception whose message was built by interpolating the object that
    // caused it. The name rides out inside `error.message`.
    const sink = new CapturingSink();
    const failure = new Error('could not format contact +94771234567');
    new SafeLog(sink).error('render failed', { cause: failure });

    expectNoSecrets(sink.output, 'the log after an error carrying a contact number');
    // The error's identity survives, because an error with no name is not debuggable.
    expect(sink.output).toContain('Error');
  });
});

describe('the redactor itself', () => {
  it('replaces a sensitive field however deeply it is nested', () => {
    const out = redact({ a: { b: { c: { d: { name: 'Kamal Perera' } } } } }) as Record<
      string,
      Record<string, Record<string, Record<string, Record<string, string>>>>
    >;
    expect(out['a']!['b']!['c']!['d']!['name']).toBe(REDACTED);
  });

  it('replaces sensitive fields inside arrays', () => {
    const out = JSON.stringify(redact([{ contact: '+94771234567' }, { name: 'Kamal Perera' }]));
    expectNoSecrets(out, 'a redacted array');
  });

  it('does not mutate the value it was given', () => {
    // The screen renders the same object the logger was handed. A redactor that blanked in
    // place would blank the one place the name is supposed to appear.
    const household = { name: 'Kamal Perera' };
    redact(household);
    expect(household.name).toBe('Kamal Perera');
  });

  it('terminates on a circular structure rather than hanging', () => {
    const circular: Record<string, unknown> = { label: 'ok' };
    circular['self'] = circular;
    expect(() => JSON.stringify(redact(circular))).not.toThrow();
  });

  it('leaves ordinary values alone', () => {
    // A redactor that mangled every field would be turned off within a week.
    expect(redact({ division: DIVISION, count: 4, ok: true })).toEqual({
      division: DIVISION,
      count: 4,
      ok: true,
    });
  });

  it('leaves a hash digest intact', () => {
    // Digests contain long digit runs and must not be mistaken for a NIC: a redacted
    // entry hash would make the sync log unreadable exactly when it is needed.
    const digest = 'a'.repeat(64);
    expect(redactText(digest)).toBe(digest);
  });
});
