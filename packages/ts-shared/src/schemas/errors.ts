/**
 * RFC 9457 Problem Details - the one error shape every SARANA service returns.
 *
 * The client never surfaces a raw HTTP status to a user. It surfaces `detail`, which the
 * server guarantees is safe to show, and keeps `correlationId` for the support path.
 */

import { z } from 'zod';
import { correlationIdSchema } from './primitives.js';

export const fieldErrorSchema = z.object({
  field: z.string(),
  code: z.string(),
  detail: z.string().nullish(),
});

export const problemDetailSchema = z.object({
  type: z.string(),
  title: z.string(),
  status: z.number().int().min(400).max(599),
  detail: z.string().nullish(),
  instance: z.string().nullish(),
  correlation_id: correlationIdSchema,
  errors: z.array(fieldErrorSchema).default([]),
});

export type ProblemDetail = z.infer<typeof problemDetailSchema>;
export type FieldError = z.infer<typeof fieldErrorSchema>;

/** Thrown by the API client for any non-2xx response. */
export class SaranaApiError extends Error {
  constructor(
    readonly problem: ProblemDetail,
    readonly response: Response,
  ) {
    super(problem.detail ?? problem.title);
    this.name = 'SaranaApiError';
  }

  get status(): number {
    return this.problem.status;
  }

  get correlationId(): string {
    return this.problem.correlation_id;
  }

  /** Field-level errors keyed by field name, for binding to form inputs. */
  get fieldErrors(): Record<string, FieldError[]> {
    const grouped: Record<string, FieldError[]> = {};
    for (const error of this.problem.errors) {
      (grouped[error.field] ??= []).push(error);
    }
    return grouped;
  }

  /** Whether retrying the same request could plausibly succeed. */
  get isRetryable(): boolean {
    return this.status === 429 || this.status >= 500;
  }
}

/**
 * Build a ProblemDetail for a transport failure that never reached a server.
 *
 * A field companion app offline in a cyclone must render the same error shape as a
 * server rejection, so one error-handling path covers both.
 */
export function transportProblem(cause: unknown, instance: string): ProblemDetail {
  return {
    type: 'https://sarana.lk/errors/transport-failure',
    title: 'Could not reach the server',
    status: 503,
    detail:
      'The request did not reach SARANA. It has been queued and will be retried when ' +
      'connectivity returns.',
    instance,
    correlation_id: 'client-offline',
    errors: [{ field: 'network', code: 'unreachable', detail: String(cause) }],
  };
}
