/**
 * Token storage and refresh.
 *
 * The store is an interface because the three surfaces keep tokens in different places:
 * the ops console in memory plus an httpOnly cookie, the public dashboard nowhere at all
 * (it is unauthenticated), and the mobile apps in the platform secure store.
 */

export interface TokenPair {
  readonly accessToken: string;
  readonly refreshToken: string;
  /** Epoch milliseconds at which the access token expires. */
  readonly expiresAt: number;
}

export interface TokenStore {
  read(): Promise<TokenPair | null>;
  write(tokens: TokenPair): Promise<void>;
  clear(): Promise<void>;
}

/** In-memory store. The default for a browser tab; nothing survives a reload. */
export class MemoryTokenStore implements TokenStore {
  #tokens: TokenPair | null = null;

  async read(): Promise<TokenPair | null> {
    return this.#tokens;
  }

  async write(tokens: TokenPair): Promise<void> {
    this.#tokens = tokens;
  }

  async clear(): Promise<void> {
    this.#tokens = null;
  }
}

/** Refresh this far before actual expiry, so a request in flight does not race it. */
export const REFRESH_SKEW_MS = 30_000;

export function isExpired(tokens: TokenPair, now: number = Date.now()): boolean {
  return tokens.expiresAt - REFRESH_SKEW_MS <= now;
}
