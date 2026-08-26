// Thin fetch wrapper: auth refresh + Idempotency-Key support, per
// docs/build-prompts/03-monorepo-scaffold.md ("a thin fetch wrapper with auth refresh
// and Idempotency-Key support"). The OpenAPI-generated typed client itself is produced
// by `make openapi` once a service has real endpoints beyond /healthz — this file is
// the transport layer that generated client sits on top of, built now because every
// service depends on it existing.

import { ApiError, problemDetailSchema } from "../schemas/errors";

export interface TokenStore {
  getAccessToken(): string | null;
  /** Called on a 401; returns the new access token, or null if refresh itself failed
   * (caller should then treat this as a real auth failure, not retry again). */
  refreshAccessToken(): Promise<string | null>;
}

export interface ApiClientOptions {
  baseUrl: string;
  tokenStore: TokenStore;
  /** Accept-Language for the request; defaults to "en" per docs/build-prompts/02-conventions.md. */
  locale?: "si" | "ta" | "en";
}

export interface RequestOptions {
  /** Required on every POST that creates or moves money or dispatches
   * (docs/build-prompts/02-conventions.md). Callers of createMutating() must pass one;
   * plain request() does not add one automatically, since not every POST needs it. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

function isMutatingWithoutIdempotencyRisk(method: string): boolean {
  return method === "GET" || method === "HEAD" || method === "OPTIONS";
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly tokenStore: TokenStore;
  private readonly locale: "si" | "ta" | "en";
  private refreshInFlight: Promise<string | null> | null = null;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.tokenStore = options.tokenStore;
    this.locale = options.locale ?? "en";
  }

  async request<T>(
    method: string,
    path: string,
    body?: unknown,
    opts: RequestOptions = {},
  ): Promise<T> {
    if (!isMutatingWithoutIdempotencyRisk(method) && body !== undefined && !opts.idempotencyKey) {
      // Not a hard failure — some POSTs genuinely don't move money or dispatch anything
      // — but callers should be deliberate about this, so surface it loudly in dev.
      console.warn(
        `[sarana] ${method} ${path} sent without an Idempotency-Key. If this creates or ` +
          "moves money or dispatches anything, that's required — see docs/build-prompts/02-conventions.md.",
      );
    }

    const response = await this.doFetch(method, path, body, opts);

    if (response.status === 401) {
      const newToken = await this.getOrRefreshToken();
      if (newToken) {
        const retried = await this.doFetch(method, path, body, opts);
        return this.parseResponse<T>(retried);
      }
    }

    return this.parseResponse<T>(response);
  }

  private async doFetch(
    method: string,
    path: string,
    body: unknown,
    opts: RequestOptions,
  ): Promise<Response> {
    const headers: Record<string, string> = {
      "Accept-Language": this.locale,
    };
    const token = this.tokenStore.getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
    if (body !== undefined) headers["Content-Type"] = "application/json";

    return fetch(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: opts.signal,
    });
  }

  private async getOrRefreshToken(): Promise<string | null> {
    // Coalesce concurrent 401s into a single refresh call, not one per in-flight request.
    if (!this.refreshInFlight) {
      this.refreshInFlight = this.tokenStore
        .refreshAccessToken()
        .finally(() => {
          this.refreshInFlight = null;
        });
    }
    return this.refreshInFlight;
  }

  private async parseResponse<T>(response: Response): Promise<T> {
    if (response.ok) {
      if (response.status === 204) return undefined as T;
      return (await response.json()) as T;
    }

    const raw = await response.json().catch(() => null);
    const parsed = problemDetailSchema.safeParse(raw);
    if (parsed.success) {
      throw new ApiError(parsed.data);
    }
    // Server didn't return a well-formed ProblemDetail — still fail loudly, but don't
    // pretend we understood the shape.
    throw new ApiError({
      type: "https://sarana.lk/errors/unknown",
      title: "Unknown error",
      status: response.status,
      detail: `Request failed with status ${response.status} and a non-conforming error body`,
      errors: [],
    });
  }
}
