// Mirrors packages/py-shared/sarana_shared/events/envelope.py::EventEnvelope. Used by
// any frontend surface that consumes events directly (e.g. an SSE stream from core-api),
// not by every app — most UI reads REST responses, not raw envelopes.

import { z } from "zod";

export const eventEnvelopeSchema = z.object({
  event_id: z.string().uuid(),
  event_type: z.string(),
  schema_version: z.number().int().default(1),
  correlation_id: z.string().uuid(),
  causation_id: z.string().uuid().nullable().default(null),
  occurred_at: z.string().datetime({ offset: true }),
  producer: z.string(),
  payload: z.record(z.string(), z.unknown()),
  trace_context: z.record(z.string(), z.unknown()).default({}),
  replay_of: z.string().uuid().nullable().default(null),
  replayed_at: z.string().datetime({ offset: true }).nullable().default(null),
});

export type EventEnvelope = z.infer<typeof eventEnvelopeSchema>;

export function isReplay(envelope: EventEnvelope): boolean {
  return envelope.replay_of !== null;
}
