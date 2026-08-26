/**
 * The SARANA API client.
 *
 * A thin wrapper over `fetch` that adds the four things every SARANA call needs:
 * bearer auth with single-flight refresh, an Idempotency-Key on operations that create
 * or move money, a correlation ID that ties the call to the server logs, and
 * Accept-Language so the response comes back in the caller's locale.
 *
 * Responses are parsed through zod, so a contract break surfaces as a named field rather
 * than as `undefined` deep inside a component.
 */

import type { z } from 'zod';

import type { Locale } from '../i18n/types.js';
import { DEFAULT_LOCALE } from '../i18n/types.js';
import {
  SaranaApiError,
  problemDetailSchema,
  transportProblem,
  type ProblemDetail,
} from '../schemas/errors.js';
import {
  IDEMPOTENCY_HEADER,
  IdempotencyKeyMissingError,
  requiresIdempotencyKey,
} from './idempotency.js';
import { MemoryTokenStore, isExpired, type TokenPair, type TokenStore } from './tokens.js';

export const CORRELATION_HEADER = 'X-Correlation-Id';

export interface ClientOptions {
  readonly baseUrl: string;
  readonly tokenStore?: TokenStore;
  readonly locale?: Locale;
  /** Overridable for tests and for React Native's fetch. */
  readonly fetch?: typeof globalThis.fetch;
  /** Called when refresh fails and the session is over. */
  readonly onAuthenticationLost?: () => void;
  readonly defaultTimeoutMs?: number;
}

export interface RequestOptions<TSchema extends z.ZodTypeAny = z.ZodTypeAny> {
  readonly method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  readonly query?: Readonly<Record<string, string | number | boolean | undefined>>;
  readonly body?: unknown;
  /** Required on POSTs that create, move money or dispatch. Reuse it when retrying. */
  readonly idempotencyKey?: string;
  readonly schema?: TSchema;
  readonly locale?: Locale;
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
  /** Skip the bearer token. Used for login and for the public read path. */
  readonly anonymous?: boolean;
}

/** Read a Problem Details body, tolerating a server that failed before producing one. */
async function readProblem(response: Response): Promise<ProblemDetail> {
  try {
    const parsed = problemDetailSchema.safeParse(await response.json());
    if (parsed.success) return parsed.data;
  } catch {
    // Fall through to the synthesised problem below.
  }
  return {
    type: 'https://sarana.lk/errors/unparseable-response',
    title: 'Unexpected response',
    status: response.status,
    detail: 'The server returned an error in an unrecognised format.',
    instance: new URL(response.url || 'http://unknown').pathname,
    correlation_id: response.headers.get(CORRELATION_HEADER) ?? 'unknown',
    errors: [],
  };
}

export class SaranaClient {
  readonly #baseUrl: string;
  readonly #tokens: TokenStore;
  readonly #fetch: typeof globalThis.fetch;
  readonly #locale: Locale;
  readonly #onAuthenticationLost?: () => void;
  readonly #defaultTimeoutMs: number;

  /** In-flight refresh, shared so a burst of 401s triggers exactly one refresh call. */
  #refreshInFlight: Promise<TokenPair | null> | null = null;

  constructor(options: ClientOptions) {
    this.#baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.#tokens = options.tokenStore ?? new MemoryTokenStore();
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.#locale = options.locale ?? DEFAULT_LOCALE;
    this.#onAuthenticationLost = options.onAuthenticationLost;
    this.#defaultTimeoutMs = options.defaultTimeoutMs ?? 15_000;
  }

  async request<TSchema extends z.ZodTypeAny>(
    path: string,
    options: RequestOptions<TSchema> & { schema: TSchema },
  ): Promise<z.infer<TSchema>>;
  async request(path: string, options?: RequestOptions): Promise<unknown>;
  async request(path: string, options: RequestOptions = {}): Promise<unknown> {
    const method = options.method ?? 'GET';

    if (requiresIdempotencyKey(method, path) && !options.idempotencyKey) {
      throw new IdempotencyKeyMissingError(method, path);
    }

    const response = await this.#send(path, method, options, { allowRefresh: true });

    if (!response.ok) {
      throw new SaranaApiError(await readProblem(response), response);
    }
    if (response.status === 204) return undefined;

    const payload: unknown = await response.json();
    return options.schema ? options.schema.parse(payload) : payload;
  }

  async #send(
    path: string,
    method: string,
    options: RequestOptions,
    context: { allowRefresh: boolean },
  ): Promise<Response> {
    const url = new URL(this.#baseUrl + path);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }

    const headers = new Headers({
      Accept: 'application/json, application/problem+json',
      'Accept-Language': options.locale ?? this.#locale,
      [CORRELATION_HEADER]: globalThis.crypto.randomUUID(),
    });

    if (options.body !== undefined) headers.set('Content-Type', 'application/json');
    if (options.idempotencyKey) headers.set(IDEMPOTENCY_HEADER, options.idempotencyKey);

    if (!options.anonymous) {
      const token = await this.#accessToken();
      if (token) headers.set('Authorization', `Bearer ${token}`);
    }

    const timeout = AbortSignal.timeout(options.timeoutMs ?? this.#defaultTimeoutMs);
    const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;

    let response: Response;
    try {
      response = await this.#fetch(url, {
        method,
        headers,
        signal,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch (cause) {
      throw new SaranaApiError(transportProblem(cause, path), Response.error());
    }

    // One retry after a refresh. A second 401 means the refresh token is gone too.
    if (response.status === 401 && context.allowRefresh && !options.anonymous) {
      const refreshed = await this.#refresh();
      if (refreshed) {
        return this.#send(path, method, options, { allowRefresh: false });
      }
      this.#onAuthenticationLost?.();
    }

    return response;
  }
  async #accessToken(): Promise<string | null> {
    const tokens = await this.#tokens.read();
    if (!tokens) return null;
    if (!isExpired(tokens)) return tokens.accessToken;
    const refreshed = await this.#refresh();
    return refreshed?.accessToken ?? null;
  }

  /** Refresh the access token. Concurrent callers share one network call. */
  async #refresh(): Promise<TokenPair | null> {
    this.#refreshInFlight ??= this.#performRefresh().finally(() => {
      this.#refreshInFlight = null;
    });
    return this.#refreshInFlight;
  }

  async #performRefresh(): Promise<TokenPair | null> {
    const current = await this.#tokens.read();
    if (!current) return null;

    try {
      const response = await this.#fetch(`${this.#baseUrl}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: current.refreshToken }),
      });
      if (!response.ok) {
        await this.#tokens.clear();
        return null;
      }
      const payload = (await response.json()) as {
        access_token: string;
        refresh_token: string;
        expires_in: number;
      };
      const tokens: TokenPair = {
        accessToken: payload.access_token,
        refreshToken: payload.refresh_token,
        expiresAt: Date.now() + payload.expires_in * 1000,
      };
      await this.#tokens.write(tokens);
      return tokens;
    } catch {
      await this.#tokens.clear();
      return null;
    }
  }

  get(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<unknown> {
    return this.request(path, { ...options, method: 'GET' });
  }

  post(path: string, options: Omit<RequestOptions, 'method'> = {}): Promise<unknown> {
    return this.request(path, { ...options, method: 'POST' });
  }

  patch(path: string, options: Omit<RequestOptions, 'method'> = {}): Promise<unknown> {
    return this.request(path, { ...options, method: 'PATCH' });
  }
}
