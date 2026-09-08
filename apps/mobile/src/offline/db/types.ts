/**
 * The database port.
 *
 * `expo-sqlite` is the implementation on a handset; `MemoryDatabase` is the one every
 * test in this package runs against. The port exists because the sync rules - ordering,
 * gaps, idempotency, the media queue's separation from the text queue - are the part
 * that has to be right, and a rule that can only be checked by booting an emulator is a
 * rule that gets checked once.
 *
 * The surface is deliberately small: parameterised statements and a transaction. No
 * query builder, no ORM. Every statement in this app is written out in full, in
 * `queries.ts`, where it can be read.
 */

export type SqlValue = string | number | null;

export interface Database {
  /** Run a statement that returns nothing. */
  execute(sql: string, params?: readonly SqlValue[]): Promise<void>;
  /** Run a statement and read every row back. */
  select<T>(sql: string, params?: readonly SqlValue[]): Promise<T[]>;
  /**
   * Run `work` inside one transaction, rolling back if it throws.
   *
   * The operation log's append and the entity write it describes go in together or not
   * at all. A device that stored an assessment with no log entry has data it will never
   * sync and no way to know.
   */
  transaction<T>(work: (tx: Database) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}

/** Wall clock, injected so the backoff and ageing tests do not sleep. */
export interface Clock {
  now(): number;
}

export const systemClock: Clock = { now: () => Date.now() };
