/**
 * Identifiers minted on the device.
 *
 * Two of them matter here. `deviceUuid7` is the client operation id: it is the
 * idempotency key end to end, so the server can be sent the same batch five times and
 * still store fifty assessments. `nextSeq` is the device's monotonic position, and the
 * server refuses to apply operations out of it.
 *
 * The UUIDv7 layout is copied from `sarana_shared.domain.ids.uuid7` rather than pulled
 * from a library, because the two have to sort the same way: the server orders a device's
 * log by `seq` but a human reading two logs side by side orders them by id.
 */

// RFC 9562 section 5.7: 48 bits unix_ts_ms | 4 version | 12 rand_a | 2 variant | 62 rand_b.
// rand_a is a counter so two ids minted in the same millisecond still sort in creation
// order, which is what makes them usable as keys.
const MAX_COUNTER = 0xfff;

let lastMs = -1;
let counter = 0;

function randomBits(count: number): bigint {
  const bytes = new Uint8Array(Math.ceil(count / 8));
  globalThis.crypto.getRandomValues(bytes);
  let value = 0n;
  for (const byte of bytes) value = (value << 8n) | BigInt(byte);
  return value & ((1n << BigInt(count)) - 1n);
}

function hex(value: bigint, width: number): string {
  return value.toString(16).padStart(width, '0');
}

/**
 * A time-ordered UUID version 7, monotonic within this JavaScript context.
 *
 * `now` is injectable because the sync tests need to mint a hundred operations across a
 * simulated two days without waiting two days.
 */
export function deviceUuid7(now: number = Date.now()): string {
  const nowMs = Math.floor(now);
  if (nowMs === lastMs) {
    counter += 1;
    if (counter > MAX_COUNTER) {
      // Counter exhausted inside one millisecond: borrow from the next one rather than
      // emit an id that sorts before the one before it.
      lastMs += 1;
      counter = 0;
    }
  } else if (nowMs > lastMs) {
    lastMs = nowMs;
    // Leave headroom to increment without overflowing within the millisecond.
    counter = Number(randomBits(10));
  } else {
    // The device clock went backwards - a real event on a handset that just got a
    // network time update. Keep issuing from the last millisecond we used, because
    // monotonic ids matter more here than a truthful timestamp.
    counter += 1;
    if (counter > MAX_COUNTER) {
      lastMs += 1;
      counter = 0;
    }
  }

  const timestamp = BigInt(lastMs) & 0xffffffffffffn;
  const randB = randomBits(62);

  const value =
    (timestamp << 80n) | (0x7n << 76n) | ((BigInt(counter) & 0xfffn) << 64n) | (0b10n << 62n) | randB;

  const digits = hex(value, 32);
  return [
    digits.slice(0, 8),
    digits.slice(8, 12),
    digits.slice(12, 16),
    digits.slice(16, 20),
    digits.slice(20),
  ].join('-');
}

/** The millisecond a device id was minted at. Used to age the operation log. */
export function uuid7Timestamp(value: string): number {
  const digits = value.replace(/-/g, '');
  if (digits.length !== 32) throw new Error(`${value} is not a UUID`);
  if (digits[12] !== '7') throw new Error(`${value} is not a version 7 UUID`);
  return Number(BigInt(`0x${digits.slice(0, 12)}`));
}

/** A local id for a row that does not have a server id yet. */
export function localId(prefix: string, now: number = Date.now()): string {
  return `${prefix}_${deviceUuid7(now)}`;
}

/** Reset the monotonic state. Tests only - never called by the app. */
export function resetIdState(): void {
  lastMs = -1;
  counter = 0;
}
