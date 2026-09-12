/**
 * The `expo-sqlite` implementation of the database port.
 *
 * The file is encrypted with SQLCipher. The key lives in the platform keystore
 * (`expo-secure-store`), which on Android is hardware-backed where the device has a TEE
 * and on iOS is the Secure Enclave-protected keychain. A field device holds a district's
 * damage assessments and the households they belong to; an unencrypted database file on a
 * handset that gets lost is a data breach with a name attached to every row.
 *
 * `PRAGMA key` must be the first statement on the connection - SQLCipher will not decrypt
 * a database that has already been read from.
 */

import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import * as SQLite from 'expo-sqlite';

import { migrate } from './schema.js';
import type { Database, SqlValue } from './types.js';

export const DATABASE_NAME = 'sarana.db';

/** Where the SQLCipher key lives. Never in AsyncStorage, never in the bundle. */
const KEY_ALIAS = 'sarana.db.key';

/**
 * Read the database key, minting one on first launch.
 *
 * 256 bits of platform randomness, hex-encoded because `PRAGMA key` takes a string and
 * a raw-byte key would have to be escaped.
 */
export async function databaseKey(): Promise<string> {
  const existing = await SecureStore.getItemAsync(KEY_ALIAS, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
  if (existing) return existing;

  const bytes = await Crypto.getRandomBytesAsync(32);
  const key = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  await SecureStore.setItemAsync(KEY_ALIAS, key, {
    // THIS_DEVICE_ONLY: the key must not travel in an iCloud or Google backup, or the
    // encrypted file and its key end up in the same restore.
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
  return key;
}

class ExpoDatabase implements Database {
  constructor(private readonly db: SQLite.SQLiteDatabase) {}

  async execute(sql: string, params: readonly SqlValue[] = []): Promise<void> {
    await this.db.runAsync(sql, params as SqlValue[]);
  }

  async select<T>(sql: string, params: readonly SqlValue[] = []): Promise<T[]> {
    return this.db.getAllAsync<T>(sql, params as SqlValue[]);
  }

  async transaction<T>(work: (tx: Database) => Promise<T>): Promise<T> {
    let result!: T;
    await this.db.withExclusiveTransactionAsync(async () => {
      result = await work(this);
    });
    return result;
  }

  async close(): Promise<void> {
    await this.db.closeAsync();
  }
}

/**
 * Open the device database, decrypt it and migrate it.
 *
 * Called once, at app start, before anything reads. Failing here is fatal and says so:
 * an app that silently falls back to an unencrypted database would be worse than one
 * that refuses to start.
 */
export async function openDeviceDatabase(): Promise<Database> {
  const key = await databaseKey();
  const raw = await SQLite.openDatabaseAsync(DATABASE_NAME);

  // First statement on the connection, before any read. Quoted with single quotes
  // because the key is hex - no escaping is possible or needed.
  await raw.execAsync(`PRAGMA key = '${key}'`);

  const db = new ExpoDatabase(raw);
  await migrate(db);
  return db;
}
