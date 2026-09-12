/**
 * The register: encrypted at rest, searchable offline, and honest about what it cannot do.
 *
 * The cipher here is a deterministic double rather than AES-GCM. That is the right choice
 * and worth saying why: these tests are about the *register's* behaviour — that no
 * plaintext reaches a column, that search matches on hashes, that a provisional household
 * survives a refresh — and swapping in a real cipher would test `expo-crypto` instead. The
 * cipher's own contract is asserted separately, at the top, so a double that failed to
 * model the real one would be caught here rather than hiding a bug in the register.
 */

import { createHash } from 'node:crypto';

import { describe, expect, it } from 'vitest';

import { migrate } from '../offline/db/schema.js';
import { openTestDatabase } from '../../test-support/node-database.js';
import {
  HouseholdRegister,
  PROVISIONAL_PREFIX,
  isProvisionalReference,
  nameTokens,
  type RegistryCipher,
  type UpstreamHousehold,
} from './household-register.js';

/**
 * A stand-in for the keystore-backed cipher.
 *
 * `encrypt` is non-deterministic and `searchHash` is not, which is the property that
 * matters: the same name in two rows must not produce the same ciphertext (or the
 * ciphertext becomes a grouping key), and the search index must be stable or it cannot be
 * searched.
 */
class TestCipher implements RegistryCipher {
  #nonce = 0;

  async encrypt(plaintext: string): Promise<string> {
    this.#nonce += 1;
    return `enc:${this.#nonce}:${Buffer.from(plaintext, 'utf8').toString('base64')}`;
  }

  async decrypt(ciphertext: string): Promise<string> {
    const [, , payload] = ciphertext.split(':');
    return Buffer.from(payload ?? '', 'base64').toString('utf8');
  }

  async searchHash(token: string): Promise<string> {
    // A real digest, not an encoding.
    //
    // The first version of this double was `hex('key::' + token).slice(0, 16)`, which is
    // prefix-preserving: `key::per` is exactly eight bytes, so `per` and `perera` produced
    // the *same* hash and the register appeared to support prefix search. It does not, and
    // a double that says it does would have hidden the one limitation this design has.
    //
    // Avalanche is the property the register depends on, so the double has to have it.
    return `h${createHash('sha256').update(`key::${token}`).digest('hex').slice(0, 16)}`;
  }
}

const DIVISION = 'LK-2-05-020-1015';

const UPSTREAM: UpstreamHousehold[] = [
  {
    id: '018f4a2b-0000-7000-8000-000000000001',
    reference_code: 'HH-LK-21-010301',
    gn_division_id: 'gn-1',
    gn_division_code: DIVISION,
    name: 'Kamal Perera',
    contact: '+94771234567',
    member_count: 4,
    has_over_70: true,
    latitude: 7.29,
    longitude: 80.63,
  },
  {
    id: '018f4a2b-0000-7000-8000-000000000002',
    reference_code: 'HH-LK-21-010302',
    gn_division_id: 'gn-1',
    gn_division_code: DIVISION,
    name: 'Nimali Perera',
    contact: '+94771234568',
    member_count: 2,
  },
  {
    id: '018f4a2b-0000-7000-8000-000000000003',
    reference_code: 'HH-LK-21-010303',
    gn_division_id: 'gn-1',
    gn_division_code: DIVISION,
    name: 'சுந்தரம் ராஜா',
    contact: '+94771234569',
    member_count: 5,
  },
];

async function register() {
  const db = openTestDatabase();
  await migrate(db);
  return { db, register: new HouseholdRegister(db, new TestCipher()) };
}

describe('the cipher double models the real one', () => {
  it('encrypts the same plaintext to different ciphertexts', async () => {
    const cipher = new TestCipher();
    const first = await cipher.encrypt('Kamal Perera');
    const second = await cipher.encrypt('Kamal Perera');
    // If this were deterministic the ciphertext would group households by name, which is
    // most of what encrypting the name was supposed to prevent.
    expect(first).not.toBe(second);
    expect(await cipher.decrypt(first)).toBe('Kamal Perera');
    expect(await cipher.decrypt(second)).toBe('Kamal Perera');
  });

  it('hashes the same token to the same hash', async () => {
    const cipher = new TestCipher();
    expect(await cipher.searchHash('perera')).toBe(await cipher.searchHash('perera'));
  });

  it('hashes a token and its prefix to different hashes', async () => {
    // The property the register's "whole tokens only" limitation rests on, and the one
    // the first version of this double got wrong - it was a prefix-preserving encoding
    // rather than a hash, so `per` matched `perera` and the register looked capable of
    // something it is not. A real keyed hash avalanches; this asserts the double does too.
    const cipher = new TestCipher();
    expect(await cipher.searchHash('per')).not.toBe(await cipher.searchHash('perera'));
  });
});

describe('nameTokens', () => {
  it('normalises case and punctuation so index and query agree', () => {
    expect(nameTokens('Kamal  Perera.')).toEqual(['kamal', 'perera']);
  });

  it('tokenises Sinhala and Tamil, which are most of this register', () => {
    // A tokeniser splitting on `[a-z]+` would index every Tamil name as nothing, and the
    // search would silently return no results for most of the division.
    expect(nameTokens('சுந்தரம் ராஜா')).toEqual(['சுந்தரம்', 'ராஜா']);
    expect(nameTokens('කමල් පෙරේරා')).toEqual(['කමල්', 'පෙරේරා']);
  });

  it('drops empty tokens rather than indexing them', () => {
    expect(nameTokens('   ')).toEqual([]);
  });
});

describe('nothing personal reaches a column in the clear', () => {
  it('stores no plaintext name or contact anywhere in the row', async () => {
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);

    const rows = await db.select<Record<string, unknown>>('SELECT * FROM household');
    const serialised = JSON.stringify(rows);

    // The strongest form: the whole row set, serialised, contains neither the names nor
    // the numbers. A column added later that happened to carry one would fail here.
    for (const household of UPSTREAM) {
      expect(serialised).not.toContain(household.name!);
      expect(serialised).not.toContain(household.contact!);
    }
    await db.close();
  });

  it('decrypts for display and only for display', async () => {
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);

    const [first] = await reg.listDivision(DIVISION);
    expect(first?.name).toBe('Kamal Perera');
    expect(first?.contact).toBe('+94771234567');
    await db.close();
  });
});

describe('search works with no signal', () => {
  it('finds a household by a whole name token', async () => {
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);

    const result = await reg.search(DIVISION, 'Perera');
    expect(result.matchedBy).toBe('name');
    expect(result.households.map((household) => household.referenceCode)).toEqual([
      'HH-LK-21-010301',
      'HH-LK-21-010302',
    ]);
    await db.close();
  });

  it('narrows on two tokens rather than widening', async () => {
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);

    const result = await reg.search(DIVISION, 'Kamal Perera');
    expect(result.households).toHaveLength(1);
    expect(result.households[0]?.referenceCode).toBe('HH-LK-21-010301');
    await db.close();
  });

  it('finds a Tamil name', async () => {
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);

    const result = await reg.search(DIVISION, 'ராஜா');
    expect(result.households[0]?.referenceCode).toBe('HH-LK-21-010303');
    await db.close();
  });

  it('finds a household by part of its reference code', async () => {
    // The reference is not personal data and is what an officer holding a paper form has
    // in front of them, so it gets a plain LIKE and supports partial matches.
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);

    const result = await reg.search(DIVISION, '010302');
    expect(result.matchedBy).toBe('reference');
    expect(result.households).toHaveLength(1);
    await db.close();
  });

  it('does not match a partial name token, and reports that it matched nothing', async () => {
    // **The documented limit of the hash index.** `Per` will not find `Perera`, because a
    // prefix search over ciphertext is not possible without a plaintext index - which is
    // the thing this design exists to avoid. `matchedBy: 'none'` is what lets the screen
    // say so instead of showing an empty list that reads as "no such household".
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);

    const result = await reg.search(DIVISION, 'Per');
    expect(result.households).toEqual([]);
    expect(result.matchedBy).toBe('none');
    await db.close();
  });

  it('lists the division when the query is empty', async () => {
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);

    const result = await reg.search(DIVISION, '   ');
    expect(result.households).toHaveLength(3);
    await db.close();
  });

  it('never reaches outside the officer’s division', async () => {
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);
    await reg.replaceDivision('LK-2-05-021-1016', [
      { ...UPSTREAM[0]!, id: 'other-1', gn_division_code: 'LK-2-05-021-1016' },
    ]);

    const result = await reg.search(DIVISION, 'Perera');
    expect(result.households.every((household) => household.gnDivisionCode === DIVISION)).toBe(true);
    await db.close();
  });
});

describe('a household the register does not have', () => {
  it('can be created offline and is marked provisional', async () => {
    // The register has gaps, and an officer who cannot record an unregistered household
    // will simply not record them - which loses exactly the households with nothing.
    const { db, register: reg } = await register();

    const created = await reg.createProvisional({
      gnDivisionId: 'gn-1',
      gnDivisionCode: DIVISION,
      name: 'Anura Silva',
      memberCount: 3,
    });

    expect(created.isProvisional).toBe(true);
    expect(isProvisionalReference(created.referenceCode)).toBe(true);
    expect(created.referenceCode.startsWith(PROVISIONAL_PREFIX)).toBe(true);
    expect(created.name).toBe('Anura Silva');
    await db.close();
  });

  it('is searchable immediately, like any other row', async () => {
    const { db, register: reg } = await register();
    await reg.createProvisional({
      gnDivisionId: 'gn-1',
      gnDivisionCode: DIVISION,
      name: 'Anura Silva',
    });

    const result = await reg.search(DIVISION, 'Silva');
    expect(result.households).toHaveLength(1);
    await db.close();
  });

  it('survives a register refresh that replaces everything else', async () => {
    // The case that decides whether the officer's own work is safe. A weekly Wi-Fi
    // refresh replaces the registry's rows; a provisional household exists only here
    // until it reconciles, so deleting it would throw away the record the register was
    // missing in the first place.
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);
    const created = await reg.createProvisional({
      gnDivisionId: 'gn-1',
      gnDivisionCode: DIVISION,
      name: 'Anura Silva',
    });

    await reg.replaceDivision(DIVISION, [UPSTREAM[0]!]);

    expect(await reg.byLocalId(created.localId)).not.toBeNull();
    const counts = await reg.counts(DIVISION);
    expect(counts).toEqual({ total: 2, provisional: 1 });
    await db.close();
  });

  it('sorts provisional households first, where the officer is looking for them', async () => {
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);
    await reg.createProvisional({ gnDivisionId: 'gn-1', gnDivisionCode: DIVISION, name: 'Anura' });

    const listed = await reg.listDivision(DIVISION);
    expect(listed[0]?.isProvisional).toBe(true);
    await db.close();
  });
});

describe('a refresh replaces the registry copy', () => {
  it('drops a household the registry no longer lists', async () => {
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);
    await reg.replaceDivision(DIVISION, [UPSTREAM[0]!]);

    const listed = await reg.listDivision(DIVISION);
    expect(listed).toHaveLength(1);
    await db.close();
  });

  it('re-encrypts a name that changed upstream', async () => {
    const { db, register: reg } = await register();
    await reg.replaceDivision(DIVISION, UPSTREAM);
    await reg.replaceDivision(DIVISION, [{ ...UPSTREAM[0]!, name: 'Kamal Fernando' }]);

    const [row] = await reg.listDivision(DIVISION);
    expect(row?.name).toBe('Kamal Fernando');
    const result = await reg.search(DIVISION, 'Fernando');
    expect(result.households).toHaveLength(1);
    await db.close();
  });
});
