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
  /**
   * WGS84, from the incident's POINT. Null when the report never carried a location.
   *
   * Nullable and stays nullable: an incident with no coordinate is real - a phone call
   * naming a village and nothing more - and dropping it from the map is different from
   * placing it at (0, 0) in the Gulf of Guinea.
   */
  lon: z.coerce.number().nullable().default(null),
  lat: z.coerce.number().nullable().default(null),
});

export type Incident = z.infer<typeof incidentSchema>;

export const incidentListSchema = z.array(incidentSchema);

/**
 * A queue row, as `QueueEntry` returns it.
 *
 * `score` and `factors` are always present: `incident-svc` computes them from the
 * published rule when nothing has stored one, rather than dropping an unranked incident
 * to the bottom of a long queue where nobody reaches it. So their presence says nothing
 * about whether an agent was involved - only the response's `assisted` flag does.
 */
export const queueRowSchema = incidentSchema.extend({
  score: z.coerce.number().nullable().default(null),
  model_version: z.string().nullable().default(null),
  /**
   * The per-factor breakdown behind the score.
   *
   * A free-shaped object because the triage model owns its factor names and the console
   * must not pin them. Rendered as name/value pairs sorted by contribution, so an operator
   * can see why row 3 outranks row 4 without leaving the screen.
   */
  factors: z.record(z.string(), z.unknown()).nullable().default(null),
});

export type QueueRow = z.infer<typeof queueRowSchema>;

/**
 * The queue, and an unmissable statement of how it was ordered.
 *
 * The endpoint returns an object, not a list. `assisted` is the **only** authority on
 * whether an agent produced this ordering - inferring it from the presence of a score
 * would always say yes, because the service always computes one.
 */
export const queueSchema = z.object({
  assisted: z.boolean(),
  /** The server's own words for the degraded state. English only; see the console note. */
  banner: z.string().nullable().default(null),
  /** The rule or model that ordered this list, e.g. a triage model version. */
  ordering: z.string(),
  entries: z.array(queueRowSchema).default([]),
});

export type Queue = z.infer<typeof queueSchema>;

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
 * The reviewer-facing text lives inside `rationale`, not at the top level - the agent
 * writes a `FlagContext` and `ledger-svc` stores it whole. `innocent_explanations` is
 * non-empty by construction on the agent side: ADR-009 requires a flag to arrive with the
 * ordinary reasons it might be there, because a flag presented alone reads as an
 * accusation and this system never accuses anybody. The console reads it defensively
 * anyway, because a flag written before that rule existed would have none.
 */
export const flagContextSchema = z.object({
  pattern_summary: z.string().default(''),
  innocent_explanations: z.array(z.string()).default([]),
  what_would_resolve_it: z.array(z.string()).default([]),
  suggested_priority: z.string().optional(),
  confidence: z.coerce.number().optional(),
  method: z.string().optional(),
});

export type FlagContext = z.infer<typeof flagContextSchema>;

export const anomalySchema = z.object({
  id: z.string(),
  subject_type: z.string(),
  subject_id: z.string(),
  detector: z.string(),
  detector_version: z.string(),
  score: z.coerce.number(),
  // Whatever the detector recorded. Parsed leniently and read through `flagContextSchema`
  // where the console needs the reviewer text.
  rationale: z.record(z.string(), z.unknown()).default({}),
  raised_at: z.string(),
  disposition: z.string(),
  disposed_by: z.string().nullable().default(null),
  disposed_at: z.string().nullable().default(null),
  disposition_note: z.string().nullable().default(null),
});

export type Anomaly = z.infer<typeof anomalySchema>;

export const anomalyListSchema = z.array(anomalySchema);

/** Every outcome but `OPEN`. `FALSE_POSITIVE` is first-class, not a failure to hide. */
export const ANOMALY_DISPOSITIONS = [
  'REVIEWED_NO_ACTION',
  'REVIEWED_ESCALATED',
  'FALSE_POSITIVE',
] as const;

export type AnomalyDisposition = (typeof ANOMALY_DISPOSITIONS)[number];

export function isOpenAnomaly(anomaly: Anomaly): boolean {
  return anomaly.disposition === 'OPEN';
}

/** Pull the reviewer-facing context out of a flag's rationale, tolerating an old shape. */
export function flagContext(anomaly: Anomaly): FlagContext {
  return flagContextSchema.parse(anomaly.rationale ?? {});
}

/** `AlertResponse` plus what the list endpoint returns alongside it. */
export const alertSchema = z.object({
  id: z.string(),
  cap_identifier: z.string(),
  status: z.string(),
  requires_human_signoff: z.boolean().default(false),
  headline: z.unknown().nullable().default(null),
  severity: z.coerce.number().nullable().default(null),
  effective_at: z.string().nullable().default(null),
  expires_at: z.string().nullable().default(null),
  created_at: z.string().nullable().default(null),
});

export type Alert = z.infer<typeof alertSchema>;

export const alertListSchema = z.array(alertSchema);

/**
 * Delivery counts, always with their denominator.
 *
 * `summary` is the server's own sentence and the console renders it verbatim. A
 * percentage computed here from the counts would be a second, drifting statement of the
 * same fact - and the rule this whole screen exists to keep is that no delivery figure
 * appears without what it is a fraction of.
 */
export const deliverySchema = z.object({
  targeted: z.number().int(),
  confirmed: z.number().int(),
  unconfirmed: z.number().int(),
  failed: z.number().int(),
  no_channel: z.number().int(),
  by_channel: z.record(z.string(), z.record(z.string(), z.number())),
  by_language: z.record(z.string(), z.number()),
  summary: z.string(),
});

export type Delivery = z.infer<typeof deliverySchema>;

/** One division that probably did not get the warning. Worst first, from the server. */
export const gapSchema = z.object({
  gn_division_code: z.string(),
  targeted: z.number().int(),
  confirmed: z.number().int(),
  confirmed_fraction: z.coerce.number(),
  summary: z.string(),
});

export type Gap = z.infer<typeof gapSchema>;

export const gapListSchema = z.array(gapSchema);

/** A ledger entry, as the public and audit views read it. */
export const ledgerEntrySchema = z.object({
  seq: z.number().int(),
  id: z.string(),
  entry_type: z.string().optional(),
  amount_lkr_cents: z.number().int().nullable().default(null),
  prev_hash: z.string(),
  entry_hash: z.string(),
  anchor_date: z.string().nullable().default(null),
  created_at: z.string().optional(),
});

export type LedgerEntry = z.infer<typeof ledgerEntrySchema>;

export const ledgerListSchema = z.array(ledgerEntrySchema);

/** A transcription or report held back for a person to look at. */
export const reviewItemSchema = z.object({
  id: z.string(),
  report_id: z.string().optional(),
  transcript: z.string().nullable().default(null),
  language: z.string().nullable().default(null),
  confidence: z.coerce.number().nullable().default(null),
  status: z.string().optional(),
  created_at: z.string().optional(),
});

export type ReviewItem = z.infer<typeof reviewItemSchema>;

export const reviewListSchema = z.array(reviewItemSchema);

/**
 * An alert template, as `GET /templates` returns it.
 *
 * `body` is the trilingual text with `{parameter}` placeholders. The two reviewer columns
 * are the trilingual review gate: a template is not publishable until a human has signed
 * the Sinhala and the Tamil, and all twelve seeded templates sit at `DRAFT` with both
 * null. That is the gate working, not a seeding oversight.
 */
export const alertTemplateSchema = z.object({
  id: z.string(),
  code: z.string(),
  hazard_type: z.string(),
  severity: z.string(),
  urgency: z.string().nullable().default(null),
  certainty: z.string().nullable().default(null),
  body: z.object({ si: z.string(), ta: z.string(), en: z.string() }),
  reviewed_by_si: z.string().nullable().default(null),
  reviewed_by_ta: z.string().nullable().default(null),
  reviewed_at: z.string().nullable().default(null),
  version: z.number().int().nullable().default(null),
  status: z.string(),
});

export type AlertTemplate = z.infer<typeof alertTemplateSchema>;

export const alertTemplateListSchema = z.array(alertTemplateSchema);

/**
 * The result of recomputing a range of the hash chain.
 *
 * `divergence` names the first `seq` that stopped adding up, with what was expected and
 * what was found. That precision is the point: "the chain is broken" is not actionable,
 * and "entry 4,117 has prev_hash X where the previous entry hashes to Y" is.
 */
export const divergenceSchema = z.object({
  seq: z.number().int(),
  reason: z.string(),
  expected: z.string().nullable().default(null),
  found: z.string().nullable().default(null),
});

export const verifySchema = z.object({
  intact: z.boolean(),
  checked: z.number().int(),
  from_seq: z.number().int(),
  to_seq: z.number().int(),
  divergence: divergenceSchema.nullable().default(null),
});

export type VerifyResult = z.infer<typeof verifySchema>;

/**
 * One day's Merkle root.
 *
 * `s3_object_lock_uri` is null until an object store is wired. That absence is the whole
 * of the external anchor - the half that survives an operator rewriting the database - so
 * the console reports it as missing rather than omitting the column.
 */
export const anchorSchema = z.object({
  date: z.string(),
  merkle_root: z.string(),
  entry_count: z.number().int(),
  first_seq: z.number().int(),
  last_seq: z.number().int(),
  prev_anchor_hash: z.string().nullable().default(null),
  s3_object_lock_uri: z.string().nullable().default(null),
  published_at: z.string().nullable().default(null),
});

export type Anchor = z.infer<typeof anchorSchema>;

export const anchorResponseSchema = z.object({
  anchors: z.array(anchorSchema),
  /** The published hashing rules, so a verifier needs no access to this source. */
  scheme: z.record(z.string(), z.string()).default({}),
});

export const assessmentSchema = z.object({
  id: z.string(),
  public_ref: z.string(),
  household_id: z.string(),
  gn_division_code: z.string(),
  hazard_event_id: z.string(),
  assessed_by: z.string(),
  assessed_at: z.string(),
  category: z.string(),
  cost_estimate_lkr_cents: z.number().int(),
  status: z.string(),
});

export type Assessment = z.infer<typeof assessmentSchema>;

export const assessmentListSchema = z.array(assessmentSchema);

/**
 * One line of a cost schedule, with the formula that produced its rate.
 *
 * `formula` is published, not internal. A household told what it is entitled to can read
 * the same formula the system used, which is the difference between a figure that is
 * contestable and one that is merely announced.
 */
export const scheduleLineSchema = z.object({
  id: z.string(),
  category: z.string(),
  subcategory: z.string().nullable().default(null),
  description: z.record(z.string(), z.string()).default({}),
  unit: z.string(),
  rate_lkr_cents: z.number().int(),
  cap_lkr_cents: z.number().int().nullable().default(null),
  formula: z.record(z.string(), z.unknown()).default({}),
});

export type ScheduleLine = z.infer<typeof scheduleLineSchema>;

export const costScheduleSchema = z.object({
  id: z.string(),
  version: z.string(),
  published_at: z.string(),
  source_ref: z.string().nullable().default(null),
  effective_from: z.string(),
  effective_to: z.string().nullable().default(null),
  lines: z.array(scheduleLineSchema).default([]),
});

export type CostSchedule = z.infer<typeof costScheduleSchema>;

export const costScheduleListSchema = z.array(costScheduleSchema);

/**
 * One recorded action, from core-api's audit search.
 *
 * `actor_type` distinguishes a person from an agent, and `agent_name` names the agent when
 * there was one. The console renders both rather than collapsing them: "the triage agent
 * proposed this" and "a dispatcher proposed this" are different facts about the same
 * incident, and an audit trail that flattened them would be useless for the question it
 * exists to answer.
 *
 * No personal name appears. `actor_id` is an identifier; the queries behind this never
 * select a name, which is a stronger guarantee than redacting one here.
 */
export const auditEntrySchema = z.object({
  id: z.string(),
  seq: z.number().int(),
  occurred_at: z.string(),
  actor_type: z.string(),
  actor_id: z.string().nullable().default(null),
  agent_name: z.string().nullable().default(null),
  action: z.string(),
  subject_type: z.string(),
  subject_id: z.string(),
  correlation_id: z.string(),
  langgraph_thread_id: z.string().nullable().default(null),
});

export type AuditEntry = z.infer<typeof auditEntrySchema>;

export const auditEntryListSchema = z.array(auditEntrySchema);

/**
 * One entitlement in a work queue, from `GET /entitlements`.
 *
 * No `calculation_trace`: the trace is the product and it belongs on the detail view where
 * somebody is about to act on it, not in a list of two hundred rows nobody reads on the
 * way past.
 *
 * `approved_levels` is levels, not a count. Two approvals at the same level are not two
 * levels, and a console that counted rows would offer an approver work the gate then
 * refuses - which teaches approvers that refusals are noise.
 */
export const entitlementSummarySchema = z.object({
  id: z.string(),
  assessment_id: z.string(),
  assessment_ref: z.string(),
  household_id: z.string(),
  gn_division_code: z.string(),
  category: z.string(),
  cost_schedule_version: z.string(),
  calculated_lkr_cents: z.number().int(),
  calculated_at: z.string(),
  status: z.string(),
  approved_levels: z.array(z.string()).default([]),
  released: z.boolean().default(false),
});

export type EntitlementSummary = z.infer<typeof entitlementSummarySchema>;

export const entitlementSummaryListSchema = z.array(entitlementSummarySchema);

/** The two approval levels `ledger-svc` accepts. */
export const APPROVAL_LEVELS = ['DS', 'DISTRICT'] as const;

export type ApprovalLevel = (typeof APPROVAL_LEVELS)[number];

/**
 * Above this, an entitlement needs District approval as well as DS.
 *
 * Mirrors `DEFAULT_DISTRICT_THRESHOLD_CENTS`. Used only to tell an approver which level
 * their signature will be; the service decides what is required, and refuses if this is
 * ever wrong.
 */
export const DISTRICT_THRESHOLD_CENTS = 50_000_000;

export function levelsRequiredFor(amountCents: number): readonly ApprovalLevel[] {
  return amountCents > DISTRICT_THRESHOLD_CENTS ? ['DS', 'DISTRICT'] : ['DS'];
}

export function outstandingLevels(row: EntitlementSummary): readonly ApprovalLevel[] {
  return levelsRequiredFor(row.calculated_lkr_cents).filter(
    (level) => !row.approved_levels.includes(level),
  );
}

/**
 * A hazard event. The thing every disaster timeline is measured from.
 *
 * `landfall_at` is T+0 and it is nullable: an event under monitoring has no landfall yet,
 * and the console must show that rather than substituting the declaration time, which
 * would put a fabricated T+0 on every figure derived from it.
 *
 * `name` stays trilingual. The console picks the locale; a server that chose one would be
 * guessing from a header that is only a hint.
 */
export const hazardEventSchema = z.object({
  id: z.string(),
  type: z.string(),
  name: z.object({ si: z.string(), ta: z.string(), en: z.string() }),
  source: z.string(),
  source_ref: z.string(),
  declared_at: z.string().nullable().default(null),
  landfall_at: z.string().nullable().default(null),
  status: z.string(),
});

export type HazardEvent = z.infer<typeof hazardEventSchema>;

export const hazardEventListSchema = z.array(hazardEventSchema);

/**
 * The event a console should anchor its timeline to.
 *
 * The most recent one that has a landfall. An event still under monitoring has no T+0, so
 * a spine drawn from it would have no anchor - and picking the newest regardless would
 * anchor the console to a depression nobody is working yet.
 */
export function anchorEvent(events: readonly HazardEvent[]): HazardEvent | null {
  return events.find((event) => event.landfall_at !== null) ?? null;
}
