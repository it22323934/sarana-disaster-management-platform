// Mirrors packages/py-shared/sarana_shared/errors.py::ProblemDetail. Every API error
// response takes this shape (RFC 9457) — parse it with this schema rather than reading
// fields off an untyped JSON body.

import { z } from "zod";

export const fieldErrorSchema = z.object({
  field: z.string(),
  code: z.string(),
});

export const problemDetailSchema = z.object({
  type: z.string(),
  title: z.string(),
  status: z.number().int(),
  detail: z.string(),
  instance: z.string().nullable().optional(),
  correlation_id: z.string().uuid().nullable().optional(),
  errors: z.array(fieldErrorSchema).default([]),
});

export type ProblemDetail = z.infer<typeof problemDetailSchema>;

export class ApiError extends Error {
  readonly problem: ProblemDetail;

  constructor(problem: ProblemDetail) {
    super(problem.detail);
    this.name = "ApiError";
    this.problem = problem;
  }
}
