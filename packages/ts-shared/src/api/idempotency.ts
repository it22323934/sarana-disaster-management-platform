/**
 * Idempotency keys.
 *
 * Required on every POST that creates, moves money, or dispatches. The server stores the
 * key with its response for 24 hours and replays it, so a retry over a bad connection
 * cannot produce two disbursements or two dispatch orders.
 *
 * The key is derived from the operation rather than minted per attempt: a retry must
 * carry the same key as the attempt it is retrying, which is the whole point.
 */

export const IDEMPOTENCY_HEADER = 'Idempotency-Key';

/** Methods and paths that require a key. Kept explicit so the rule is auditable. */
const REQUIRES_KEY = [
  /^\/api\/v1\/incidents$/,
  /^\/api\/v1\/incidents\/[^/]+\/dispatches$/,
  /^\/api\/v1\/dispatches\/[^/]+\/commit$/,
  /^\/api\/v1\/assessments$/,
  /^\/api\/v1\/entitlements$/,
  /^\/api\/v1\/entitlements\/[^/]+\/approvals$/,
  /^\/api\/v1\/disbursements$/,
  /^\/api\/v1\/disbursements\/[^/]+\/release$/,
  /^\/api\/v1\/grievances$/,
  /^\/api\/v1\/alerts$/,
  /^\/api\/v1\/alerts\/[^/]+\/dispatch$/,
];

export function requiresIdempotencyKey(method: string, path: string): boolean {
  if (method.toUpperCase() !== 'POST') return false;
  return REQUIRES_KEY.some((pattern) => pattern.test(path));
}

/**
 * Mint a key for a new operation.
 *
 * `crypto.randomUUID` is available in every runtime SARANA targets: modern browsers,
 * Node 20+, and React Native via `expo-crypto`'s polyfill.
 */
export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

export class IdempotencyKeyMissingError extends Error {
  constructor(
    readonly method: string,
    readonly path: string,
  ) {
    super(
      `${method} ${path} creates, moves money or dispatches, and needs an ` +
        `${IDEMPOTENCY_HEADER}. Pass one in the request options - and reuse the same ` +
        'key when retrying, or the retry becomes a second operation.',
    );
    this.name = 'IdempotencyKeyMissingError';
  }
}
