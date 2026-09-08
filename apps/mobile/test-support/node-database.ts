/**
 * A `Database` backed by Node's built-in SQLite, for tests.
 *
 * Not a fake. The tests in this package run the real DDL from `schema.ts`, the real
 * CHECK constraints and the real SQL from `queries.ts` against a real SQLite engine -
 * the same engine `expo-sqlite` ships. What a test here cannot see is the SQLCipher
 * layer and the JSI bridge; everything above them behaves identically.
 *
 * Nothing in `src/` imports this file, so Metro never bundles `node:sqlite`.
 */

import { createRequire } from 'node:module';
import type { DatabaseSync as DatabaseSyncType } from 'node:sqlite';

import type { Database, SqlValue } from '../src/offline/db/types.js';

// Loaded through `createRequire` rather than imported. Vite's list of Node builtins
// predates `node:sqlite`, so a static import is resolved as a package called "sqlite"
// and the whole suite fails to collect.
const { DatabaseSync } = createRequire(import.meta.url)('node:sqlite') as {
  DatabaseSync: new (path: string) => DatabaseSyncType;
};

class NodeDatabase implements Database {
  #depth = 0;

  constructor(private readonly db: DatabaseSyncType) {}

  async execute(sql: string, params: readonly SqlValue[] = []): Promise<void> {
    if (params.length === 0) {
      this.db.exec(sql);
      return;
    }
    this.db.prepare(sql).run(...(params as SqlValue[]));
  }

  async select<T>(sql: string, params: readonly SqlValue[] = []): Promise<T[]> {
    return this.db.prepare(sql).all(...(params as SqlValue[])) as T[];
  }

  /**
   * Nested transactions become savepoints.
   *
   * The sync engine calls `transaction` from inside a transaction in one place - the
   * batch commit, which wraps per-operation writes - and SQLite refuses a nested BEGIN.
   * `expo-sqlite`'s `withExclusiveTransactionAsync` reentrantly joins the outer one, so
   * this does the equivalent.
   */
  async transaction<T>(work: (tx: Database) => Promise<T>): Promise<T> {
    const name = `sp_${this.#depth}`;
    const outermost = this.#depth === 0;
    this.db.exec(outermost ? 'BEGIN' : `SAVEPOINT ${name}`);
    this.#depth += 1;
    try {
      const result = await work(this);
      this.#depth -= 1;
      this.db.exec(outermost ? 'COMMIT' : `RELEASE ${name}`);
      return result;
    } catch (error) {
      this.#depth -= 1;
      this.db.exec(outermost ? 'ROLLBACK' : `ROLLBACK TO ${name}`);
      throw error;
    }
  }

  async close(): Promise<void> {
    this.db.close();
  }
}

/** An empty in-memory database. Nothing is migrated; the caller decides. */
export function openTestDatabase(): Database {
  return new NodeDatabase(new DatabaseSync(':memory:'));
}
