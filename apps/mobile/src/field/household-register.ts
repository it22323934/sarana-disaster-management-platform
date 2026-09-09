/**
 * The GN division's household register, on the device, encrypted, and searchable offline.
 *
 * Three requirements pull against each other here and the resolution is the substance of
 * this file.
 *
 *   **It has to work with no signal.** Step one of the assessment form is "select
 *   household". A form that needed a network for that would be unusable in exactly the
 *   divisions that most need assessing.
 *
 *   **Names and numbers must not sit on the handset in the clear.** Two thousand
 *   households' names and phone numbers on a personal phone is a data-protection incident
 *   waiting for a theft. `name_cipher` and `contact_cipher` are the only columns that hold
 *   them, and there is no plaintext column to fall back to.
 *
 *   **Search still has to be instant.** Encrypted text cannot be searched, so the register
 *   carries `name_search`: a keyed hash of each normalised name token, joined. A query
 *   hashes the officer's search term the same way and matches on the hash.
 *
 * **What the hash index gives up, stated plainly.** It supports exact token matches and
 * prefix matches over whole tokens, and nothing else — no substring search, no fuzzy
 * matching, no "starts with three letters". An officer typing `Per` will not find
 * `Perera`, and the search screen says so rather than showing an empty list. The
 * alternative is a plaintext index, which is the thing this design exists to avoid; the
 * honest trade is a narrower search that does not leak.
 *
 * It is also not anonymity. Anyone holding the device *and* the key can hash a candidate
 * name and confirm whether it is in the register. That is a real limitation and the reason
 * the key lives in the OS keystore rather than in the database: the attacker who has the
 * SQLite file has the hashes, not the key.
 */

import type { Database, SqlValue } from '../offline/db/types.js';
import { deviceUuid7 } from '../offline/ids.js';

/**
 * Encrypt and decrypt a short string, and derive the search hash.
 *
 * A port so the register can be tested without a keystore. On a handset this is AES-GCM
 * with a key from `expo-secure-store`, which is backed by the Android Keystore; in tests it
 * is a deterministic double so the assertions are about the register's behaviour rather
 * than about a cipher nobody here wrote.
 *
 * `searchHash` is separate from `encrypt` on purpose: encryption must be non-deterministic
 * (the same name in two rows must not produce the same ciphertext, or the ciphertext is a
 * grouping key), and the search index must be deterministic or it cannot be searched. Two
 * different properties, so two different functions.
 */
export interface RegistryCipher {
  encrypt(plaintext: string): Promise<string>;
  decrypt(ciphertext: string): Promise<string>;
  /** Deterministic keyed hash of one normalised token. */
  searchHash(token: string): Promise<string>;
}

export interface HouseholdRow {
  readonly local_id: string;
  readonly server_id: string | null;
  readonly reference_code: string;
  readonly gn_division_id: string;
  readonly gn_division_code: string;
  readonly name_cipher: string | null;
  readonly contact_cipher: string | null;
  readonly name_search: string;
  readonly member_count: number | null;
  readonly has_over_70: number;
  readonly has_under_5: number;
  readonly has_mobility_impairment: number;
  readonly latitude: number | null;
  readonly longitude: number | null;
  readonly is_provisional: number;
  readonly synced_at: string | null;
  readonly updated_at: string;
}

/** A household as a screen shows it: names decrypted, nothing else changed. */
export interface Household {
  readonly localId: string;
  readonly serverId: string | null;
  readonly referenceCode: string;
  readonly gnDivisionCode: string;
  readonly name: string | null;
  readonly contact: string | null;
  readonly memberCount: number | null;
  readonly hasOver70: boolean;
  readonly hasUnder5: boolean;
  readonly hasMobilityImpairment: boolean;
  readonly latitude: number | null;
  readonly longitude: number | null;
  readonly isProvisional: boolean;
}

export interface UpstreamHousehold {
  readonly id: string;
  readonly reference_code: string;
  readonly gn_division_id: string;
  readonly gn_division_code: string;
  readonly name?: string | null;
  readonly contact?: string | null;
  readonly member_count?: number | null;
  readonly has_over_70?: boolean;
  readonly has_under_5?: boolean;
  readonly has_mobility_impairment?: boolean;
  readonly latitude?: number | null;
  readonly longitude?: number | null;
}

/**
 * Normalise a name into search tokens.
 *
 * Lowercased, punctuation dropped, split on whitespace. Applied identically when indexing
 * and when searching, because the hash of `Perera` and the hash of `perera.` have to be the
 * same hash or the index finds nothing.
 *
 * Unicode-aware: Sinhala and Tamil names are the majority of this register, and a tokeniser
 * that split on `[a-z]+` would index them as one empty string each.
 */
export function nameTokens(value: string): string[] {
  return value
    .normalize('NFC')
    .toLowerCase()
    .split(/[\s\p{P}\p{S}]+/u)
    .map((token) => token.trim())
    .filter((token) => token.length > 0);
}

const COLUMNS =
  'local_id, server_id, reference_code, gn_division_id, gn_division_code, name_cipher, ' +
  'contact_cipher, name_search, member_count, has_over_70, has_under_5, ' +
  'has_mobility_impairment, latitude, longitude, is_provisional, synced_at, updated_at';

/**
 * A household created by an officer because the register did not have one.
 *
 * The register has gaps and this is the escape hatch for them. `PROV-` is deliberately
 * visible in the reference so nobody mistakes it for a registry code: it reconciles
 * server-side on sync and the officer needs to know which of their records is still
 * waiting on that.
 */
export const PROVISIONAL_PREFIX = 'PROV-';

export function isProvisionalReference(reference: string): boolean {
  return reference.startsWith(PROVISIONAL_PREFIX);
}

export class HouseholdRegister {
  constructor(
    private readonly db: Database,
    private readonly cipher: RegistryCipher,
  ) {}

  /**
   * Replace the cached register for one division.
   *
   * A full replace rather than a merge, because the server's copy is authoritative for
   * registered households and a merge would resurrect a row the registry had removed.
   *
   * **Provisional households are kept.** They exist only on this device until they
   * reconcile, so deleting them here would throw away the officer's own work — the exact
   * records the register was missing in the first place.
   */
  async replaceDivision(
    gnDivisionCode: string,
    households: readonly UpstreamHousehold[],
    { now = Date.now() }: { now?: number } = {},
  ): Promise<number> {
    const at = new Date(now).toISOString();

    const prepared = await Promise.all(
      households.map(async (household) => ({
        household,
        nameCipher: household.name ? await this.cipher.encrypt(household.name) : null,
        contactCipher: household.contact ? await this.cipher.encrypt(household.contact) : null,
        search: household.name ? await this.#searchIndex(household.name) : '',
      })),
    );

    await this.db.transaction(async (tx) => {
      await tx.execute(
        'DELETE FROM household WHERE gn_division_code = ? AND is_provisional = 0',
        [gnDivisionCode],
      );

      for (const { household, nameCipher, contactCipher, search } of prepared) {
        await tx.execute(
          `INSERT OR REPLACE INTO household (${COLUMNS}) ` +
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
          [
            `hh_${household.id}`,
            household.id,
            household.reference_code,
            household.gn_division_id,
            household.gn_division_code,
            nameCipher,
            contactCipher,
            search,
            household.member_count ?? null,
            household.has_over_70 ? 1 : 0,
            household.has_under_5 ? 1 : 0,
            household.has_mobility_impairment ? 1 : 0,
            household.latitude ?? null,
            household.longitude ?? null,
            0,
            at,
            at,
          ],
        );
      }
    });

    return prepared.length;
  }

  /**
   * Create a household the register does not have.
   *
   * Returns the local row. It is not appended to the operation log here: the household is
   * created *as part of* an assessment, and the assessment's own operation carries it, so
   * that a device cannot sync a household with no assessment attached to explain it.
   */
  async createProvisional(
    input: {
      readonly gnDivisionId: string;
      readonly gnDivisionCode: string;
      readonly name?: string | null;
      readonly contact?: string | null;
      readonly memberCount?: number | null;
      readonly latitude?: number | null;
      readonly longitude?: number | null;
    },
    { now = Date.now() }: { now?: number } = {},
  ): Promise<Household> {
    const localId = `hh_local_${deviceUuid7(now)}`;
    const at = new Date(now).toISOString();
    // Short and readable: an officer reads this back over a radio when the record is
    // queried, so the whole UUID would be useless.
    const reference = `${PROVISIONAL_PREFIX}${localId.slice(-8).toUpperCase()}`;

    await this.db.execute(
      `INSERT INTO household (${COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        localId,
        null,
        reference,
        input.gnDivisionId,
        input.gnDivisionCode,
        input.name ? await this.cipher.encrypt(input.name) : null,
        input.contact ? await this.cipher.encrypt(input.contact) : null,
        input.name ? await this.#searchIndex(input.name) : '',
        input.memberCount ?? null,
        0,
        0,
        0,
        input.latitude ?? null,
        input.longitude ?? null,
        1,
        null,
        at,
      ],
    );

    const created = await this.byLocalId(localId);
    if (!created) throw new Error('the provisional household was not written');
    return created;
  }

  /** One household, decrypted for display. */
  async byLocalId(localId: string): Promise<Household | null> {
    const [row] = await this.db.select<HouseholdRow>(
      `SELECT ${COLUMNS} FROM household WHERE local_id = ?`,
      [localId],
    );
    return row ? this.#decrypt(row) : null;
  }

  /** Every household in the division, reference order. The list screen's query. */
  async listDivision(gnDivisionCode: string, limit = 500): Promise<Household[]> {
    const rows = await this.db.select<HouseholdRow>(
      `SELECT ${COLUMNS} FROM household WHERE gn_division_code = ? ` +
        'ORDER BY is_provisional DESC, reference_code LIMIT ?',
      [gnDivisionCode, limit],
    );
    return Promise.all(rows.map((row) => this.#decrypt(row)));
  }

  /**
   * Search the register offline.
   *
   * A reference-code search is a plain `LIKE` — the code is not personal data and is what
   * an officer holding a paper form has in front of them. A name search hashes the term
   * and matches the hash, which is why it is whole-token only.
   *
   * `matchedBy` comes back so the screen can tell the officer *why* a row matched, and — the
   * part that matters — can say "name search matches whole words only" when a name query
   * returns nothing.
   */
  async search(
    gnDivisionCode: string,
    query: string,
    { limit = 50 }: { limit?: number } = {},
  ): Promise<{ readonly households: Household[]; readonly matchedBy: 'reference' | 'name' | 'none' }> {
    const trimmed = query.trim();
    if (trimmed.length === 0) {
      return { households: await this.listDivision(gnDivisionCode, limit), matchedBy: 'none' };
    }

    const byReference = await this.db.select<HouseholdRow>(
      `SELECT ${COLUMNS} FROM household WHERE gn_division_code = ? AND reference_code LIKE ? ` +
        'ORDER BY reference_code LIMIT ?',
      [gnDivisionCode, `%${trimmed.toUpperCase()}%`, limit],
    );
    if (byReference.length > 0) {
      return {
        households: await Promise.all(byReference.map((row) => this.#decrypt(row))),
        matchedBy: 'reference',
      };
    }

    const tokens = nameTokens(trimmed);
    if (tokens.length === 0) return { households: [], matchedBy: 'none' };

    // Every token must be present, so "kamal perera" narrows rather than widens. Each
    // token is delimited by spaces in the index, so the LIKE cannot match a partial hash.
    const hashes = await Promise.all(tokens.map((token) => this.cipher.searchHash(token)));
    const clauses = hashes.map(() => "(' ' || name_search || ' ') LIKE ?").join(' AND ');
    const params: SqlValue[] = [gnDivisionCode, ...hashes.map((hash) => `% ${hash} %`), limit];

    const rows = await this.db.select<HouseholdRow>(
      `SELECT ${COLUMNS} FROM household WHERE gn_division_code = ? AND ${clauses} ` +
        'ORDER BY reference_code LIMIT ?',
      params,
    );

    return {
      households: await Promise.all(rows.map((row) => this.#decrypt(row))),
      matchedBy: rows.length > 0 ? 'name' : 'none',
    };
  }

  /** How many households this device holds for the division, and how many are provisional. */
  async counts(gnDivisionCode: string): Promise<{ total: number; provisional: number }> {
    const [row] = await this.db.select<{ total: number; provisional: number }>(
      'SELECT COUNT(*) AS total, ' +
        'COALESCE(SUM(CASE WHEN is_provisional = 1 THEN 1 ELSE 0 END), 0) AS provisional ' +
        'FROM household WHERE gn_division_code = ?',
      [gnDivisionCode],
    );
    return { total: row?.total ?? 0, provisional: row?.provisional ?? 0 };
  }

  async #searchIndex(name: string): Promise<string> {
    const hashes = await Promise.all(nameTokens(name).map((token) => this.cipher.searchHash(token)));
    return hashes.join(' ');
  }

  async #decrypt(row: HouseholdRow): Promise<Household> {
    return {
      localId: row.local_id,
      serverId: row.server_id,
      referenceCode: row.reference_code,
      gnDivisionCode: row.gn_division_code,
      name: row.name_cipher ? await this.cipher.decrypt(row.name_cipher) : null,
      contact: row.contact_cipher ? await this.cipher.decrypt(row.contact_cipher) : null,
      memberCount: row.member_count,
      hasOver70: row.has_over_70 === 1,
      hasUnder5: row.has_under_5 === 1,
      hasMobilityImpairment: row.has_mobility_impairment === 1,
      latitude: row.latitude,
      longitude: row.longitude,
      isProvisional: row.is_provisional === 1,
    };
  }
}
