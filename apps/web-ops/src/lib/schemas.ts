/**
 * The console's view of the API contracts.
 *
 * Hand-written against the FastAPI response models rather than generated, because
 * `packages/ts-shared/src/api/generated.ts` is produced by `make openapi` and does not
 * exist in a checkout that has not run it. Hand-written schemas also let each field carry
 * the note that says what it means here — `unservable` is not self-explanatory from its
 * type.
 *
 * Everything is `.passthrough()`-free and strict about what it needs, but tolerant about
 * extra fields: a service that adds a column should not break the console, while a
 * service that removes one the console renders should break it loudly at the boundary.
 */

import { z } from 'zod';

/** `PROPOSED | AWAITING_SIGNOFF | APPROVED | REJECTED | RELEASED | COMPLETED`. */
export const planStatusSchema = z.enum([
  'PROPOSED',
  'AWAITING_SIGNOFF',
  'APPROVED',
  'REJECTED',
  'RELEASED',
  'COMPLETED',
]);

export type PlanStatus = z.infer<typeof planStatusSchema>;

/**
 * The statuses that mean a person still has to act.
 *
 * Both, not just `AWAITING_SIGNOFF`. A plan sitting in `PROPOSED` is equally un-acted-on
 * from a dispatcher's point of view, and a banner that counted only one of them would
 * report zero while work waited.
 */
export const PENDING_PLAN_STATUSES: readonly PlanStatus[] = ['PROPOSED', 'AWAITING_SIGNOFF'];

export const dispatchPlanSchema = z.object({
  id: z.string(),
  incident_ids: z.array(z.string()),
  responder_ids: z.array(z.string()),
  estimated_duration_min: z.number().int().nullable(),
  proposed_at: z.string(),
  proposed_by_agent: z.string(),
  status: planStatusSchema,
  signed_off_by: z.string().nullable().default(null),
  signed_off_at: z.string().nullable().default(null),
  rejection_reason: z.string().nullable().default(null),
});

export type DispatchPlan = z.infer<typeof dispatchPlanSchema>;

export const dispatchPlanListSchema = z.array(dispatchPlanSchema);

/** The fixed taxonomy `incident-svc` accepts. Free text is a separate `note` field. */
export const REJECTION_REASONS = [
  'INCORRECT_PRIORITISATION',
  'RESPONDER_UNAVAILABLE',
  'ROUTE_IMPASSABLE',
  'DUPLICATE_PLAN',
  'INSUFFICIENT_INFORMATION',
  'SAFETY_CONCERN',
  'OTHER',
] as const;

export type RejectionReason = (typeof REJECTION_REASONS)[number];

export const decisionResponseSchema = z.object({
  plan_id: z.string(),
  status: z.string(),
  decided_by: z.string(),
  decided_at: z.string(),
  /**
   * False when no agent reasoning thread was attached to this plan.
   *
   * Surfaced in the UI rather than swallowed: it is the difference between "the agent has
   * been told the outcome and will learn from it" and "a plan was decided and the thread
   * that proposed it is still sitting interrupted".
   */
  graph_resumed: z.boolean(),
  reason: z.string().nullable().default(null),
});

export const incidentSchema = z.object({
  id: z.string(),
  public_ref: z.string(),
  gn_division_code: z.string(),
  type: z.string(),
  subtype: z.string().nullable().default(null),
  summary: z.unknown().nullable().default(null),
  people_at_risk: z.number().int(),
  severity: z.number().int().min(0).max(4),
  status: z.string(),
  first_reported_at: z.string(),
  location_confidence: z.coerce.number().nullable().default(null),
});

export type Incident = z.infer<typeof incidentSchema>;

export const incidentListSchema = z.array(incidentSchema);

/**
 * A queue row.
 *
 * `incident-svc`'s `/incidents/queue` returns the incident plus its triage score and the
 * factor breakdown when a triage agent produced one. Both are optional here because the
 * agent has no adapters yet: today the endpoint answers with the deterministic ordering
 * and no factors, and the console has to say so rather than presenting a rule-based rank
 * as if it were a model's.
 */
export const queueRowSchema = incidentSchema.extend({
  triage_score: z.coerce.number().nullable().default(null),
  triage_factors: z
    .array(
      z.object({
        name: z.string(),
        weight: z.coerce.number(),
        value: z.coerce.number(),
        contribution: z.coerce.number(),
      }),
    )
    .nullable()
    .default(null),
});

export type QueueRow = z.infer<typeof queueRowSchema>;

export const queueSchema = z.array(queueRowSchema);

export const responderSchema = z.object({
  id: z.string(),
  callsign: z.string(),
  type: z.string(),
  status: z.string(),
  gn_division_code: z.string().nullable().default(null),
});

export type Responder = z.infer<typeof responderSchema>;

export const responderListSchema = z.array(responderSchema);

/** `EntitlementOut`. `calculation_trace` is the full working, and the money gate shows it. */
export const entitlementSchema = z.object({
  id: z.string(),
  assessment_id: z.string(),
  assessment_ref: z.string(),
  household_id: z.string(),
  gn_division_code: z.string(),
  cost_schedule_version: z.string(),
  calculated_lkr_cents: z.number().int(),
  calculation_trace: z.record(z.string(), z.unknown()),
  calculated_at: z.string(),
  status: z.string(),
  requires_district_approval: z.boolean(),
  approvals: z
    .array(
      z.object({
        level: z.string().optional(),
        approver_id: z.string().optional(),
        decision: z.string().optional(),
        decided_at: z.string().optional(),
      }),
    )
    .default([]),
});

export type Entitlement = z.infer<typeof entitlementSchema>;

export const disbursementSchema = z.object({
  seq: z.number().int(),
  id: z.string(),
  entitlement_id: z.string(),
  amount_lkr_cents: z.number().int(),
  released_by: z.string(),
  released_at: z.string(),
  payment_rail: z.string(),
  payment_ref: z.string().nullable().default(null),
  prev_hash: z.string(),
  entry_hash: z.string(),
  citizen_confirmed: z.boolean().default(false),
  /** Every rail in Phase 1 is a mock, and every reference says so. */
  simulated: z.boolean().default(true),
});

export type Disbursement = z.infer<typeof disbursementSchema>;

export const disbursementListSchema = z.array(disbursementSchema);

export const grievanceSchema = z.object({
  id: z.string(),
  public_ref: z.string().optional(),
  entitlement_id: z.string().nullable().default(null),
  status: z.string(),
  category: z.string().optional(),
  raised_at: z.string().optional(),
});

export type Grievance = z.infer<typeof grievanceSchema>;

export const grievanceListSchema = z.array(grievanceSchema);

/** Statuses that block a release. Anything not resolved is open, by design. */
export const OPEN_GRIEVANCE_STATUSES = ['OPEN', 'ASSIGNED', 'IN_PROGRESS', 'ESCALATED'] as const;

export function isOpenGrievance(grievance: Grievance): boolean {
  return (OPEN_GRIEVANCE_STATUSES as readonly string[]).includes(grievance.status);
}

/**
 * An anomaly flag.
 *
 * `innocent_explanations` is not decoration. ADR-009 requires that a flag is shown with
 * the ordinary reasons it might be there, because a flag presented alone reads as an
 * accusation and this system never accuses anybody.
 */
export const anomalySchema = z.object({
  id: z.string(),
  detector: z.string(),
  gn_division_code: z.string().nullable().default(null),
  entitlement_id: z.string().nullable().default(null),
  severity: z.string().optional(),
  flagged_at: z.string().optional(),
  disposition: z.string().nullable().default(null),
  innocent_explanations: z.array(z.string()).default([]),
  what_would_resolve_it: z.string().nullable().default(null),
});

export type Anomaly = z.infer<typeof anomalySchema>;

export const anomalyListSchema = z.array(anomalySchema);
