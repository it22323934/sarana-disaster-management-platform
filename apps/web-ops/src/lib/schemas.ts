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

/** One responder's assigned sequence of stops, in the order they will be reached. */
export const responderRouteSchema = z.object({
  responder_id: z.string(),
  stops: z
    .array(
      z.object({
        incident_id: z.string(),
        sequence: z.number().int(),
        eta_minutes: z.coerce.number(),
      }),
    )
    .default([]),
  total_minutes: z.coerce.number().default(0),
});

export type ResponderRoute = z.infer<typeof responderRouteSchema>;

/**
 * An incident the solver could not fit, and why.
 *
 * Rendered prominently rather than as a footnote. It is the entry a dispatcher escalates
 * to a different agency, and a gate screen that buried it would let somebody approve a
 * plan while a household they never saw was left unreached.
 */
export const unservableSchema = z.object({
  incident_id: z.string(),
  reason: z.string(),
  detail: z.string().default(''),
});

export type Unservable = z.infer<typeof unservableSchema>;

/**
 * Why one incident sits where it does in the plan's ranking.
 *
 * `factors` stays free-shaped because the triage model owns its factor names. The console
 * walks it structurally and renders every key, because the term it does not recognise is
 * the one the model just started using.
 */
export const incidentFactorsSchema = z.object({
  incident_id: z.string(),
  rank: z.number().int().nullable().default(null),
  score: z.coerce.number().nullable().default(null),
  dispatchability: z.coerce.number().nullable().default(null),
  dispatchable: z.boolean().nullable().default(null),
  model_version: z.string().nullable().default(null),
  method: z.string().nullable().default(null),
  factors: z.record(z.string(), z.unknown()).default({}),
  explanation: z.string().nullable().default(null),
});

export type IncidentFactors = z.infer<typeof incidentFactorsSchema>;

/**
 * The agent's own account of the plan, read from `dispatch_plan.route`.
 *
 * **Null and empty are different claims.** Null means nothing recorded a reason; an empty
 * factor list under a "why these are ranked here" heading would say the agent weighed
 * nothing, which is worse and untrue. The gate screen shows the degraded banner for null
 * and the breakdown for anything else.
 */
export const planReasoningSchema = z.object({
  routes: z.array(responderRouteSchema).default([]),
  unservable: z.array(unservableSchema).default([]),
  factors: z.array(incidentFactorsSchema).default([]),
  method: z.string().nullable().default(null),
  status: z.string().nullable().default(null),
  rationale: z.string().nullable().default(null),
  /** How the prose was produced. "TEMPLATE" and a model name are weighed differently. */
  rationale_method: z.string().nullable().default(null),
});

export type PlanReasoning = z.infer<typeof planReasoningSchema>;

export const dispatchPlanDetailSchema = dispatchPlanSchema.extend({
  langgraph_thread_id: z.string().nullable().default(null),
  reasoning: planReasoningSchema.nullable().default(null),
});

export type DispatchPlanDetail = z.infer<typeof dispatchPlanDetailSchema>;

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
 * One report behind an incident, with the transcription that decided its fate.
 *
 * **The original-language text is the point.** A dispatcher reading only the English
 * translation of a Tamil report is reading a machine's guess at what a frightened person
 * said, with no way to tell how good the guess was. So `text_original` travels with its
 * `detected_language` and its `confidence`, and the console renders it with `lang` set so
 * it appears in the right face and a screen reader uses the right voice.
 *
 * No field here identifies the sender. The query behind it never selects the number hash
 * or the household id, which is a stronger guarantee than redacting one here.
 */
export const linkedReportSchema = z.object({
  report_id: z.string(),
  channel: z.string(),
  received_at: z.string(),
  /** How closely dedup matched. Null when a human made the link. */
  similarity: z.coerce.number().nullable().default(null),
  linked_by: z.string().nullable().default(null),
  raw_text: z.string().nullable().default(null),
  reported_language: z.string().nullable().default(null),
  /**
   * An object key, not a signed URL.
   *
   * Media signing is not wired (file 08), so this cannot be played. The console says the
   * recording exists and that playback needs the object store, rather than rendering an
   * audio element that silently fails - an operator who presses play and hears nothing
   * concludes the recording is empty.
   */
  raw_audio_uri: z.string().nullable().default(null),
  location_source: z.string().nullable().default(null),
  location_accuracy_m: z.number().int().nullable().default(null),
  processing_status: z.string().nullable().default(null),
  detected_language: z.string().nullable().default(null),
  text_original: z.string().nullable().default(null),
  text_en: z.string().nullable().default(null),
  confidence: z.coerce.number().nullable().default(null),
  needs_human_review: z.boolean().nullable().default(null),
  reviewed_at: z.string().nullable().default(null),
});

export type LinkedReport = z.infer<typeof linkedReportSchema>;

/** Another incident dedup folded into the same cluster as this one. */
export const clusterSiblingSchema = z.object({
  id: z.string(),
  public_ref: z.string(),
  status: z.string(),
  type: z.string(),
  severity: z.number().int(),
  gn_division_code: z.string(),
  is_cluster_primary: z.boolean(),
  first_reported_at: z.string(),
});

export type ClusterSibling = z.infer<typeof clusterSiblingSchema>;

/**
 * One incident with its linked reports and the cluster dedup put it in.
 *
 * `GET /incidents/{id}` promised linked reports from the day it was written and joined
 * none, so both the context pane and the detail screen had to say so on screen. The
 * service now returns them and this is the shape.
 */
export const incidentDetailSchema = incidentSchema.extend({
  cluster_id: z.string().nullable().default(null),
  is_cluster_primary: z.boolean().nullable().default(null),
  verified_at: z.string().nullable().default(null),
  resolved_at: z.string().nullable().default(null),
  correlation_id: z.string().nullable().default(null),
  reports: z.array(linkedReportSchema).default([]),
  dedup_links: z.array(clusterSiblingSchema).default([]),
});

export type IncidentDetail = z.infer<typeof incidentDetailSchema>;

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

/**
 * A responder, as `GET /responders` returns it.
 *
 * The field names here were guessed once - `callsign` and `gn_division_code`, neither of
 * which this service has ever had - and the guess failed at this zod boundary, which
 * quietly emptied the responder list on the dispatch gate. The endpoint now carries a
 * response model so the vocabulary is a contract rather than an assumption.
 *
 * `lon`/`lat` are the last reported position and stay nullable: a team that has not
 * reported one is not at (0, 0), and the map counts what it cannot place.
 */
export const responderSchema = z.object({
  id: z.string(),
  /** The organisation, e.g. "Sri Lanka Navy". There is no per-unit callsign in the schema. */
  org: z.string(),
  type: z.string(),
  capacity: z.number().int().default(0),
  status: z.string(),
  home_gn_division_id: z.string().nullable().default(null),
  lon: z.coerce.number().nullable().default(null),
  lat: z.coerce.number().nullable().default(null),
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
  assigned_ds_division_code: z.string().nullable().default(null),
  /**
   * When this grievance was due, and whether it is late.
   *
   * The clock starts when the household complains and an assignment does not restart it -
   * `ledger-svc` is explicit about that, because a restarting clock would let a grievance
   * be kept indefinitely fresh by passing it between offices. Both are on the queue row so
   * the oldest breach is visible without opening anything.
   */
  sla_due_at: z.string().nullable().default(null),
  sla_breached: z.boolean().default(false),
  resolved_at: z.string().nullable().default(null),
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

/**
 * One division's forecast impact, and what moved it there.
 *
 * `drivers` is required non-empty by a CHECK constraint on the table and it is the reason
 * this screen is worth having. "150mm of rain" is a meteorological fact; "these 40
 * divisions, this many households, this likely loss of road access, because the catchment
 * is already at capacity" is a decision. The console renders every driver key it is given
 * rather than a known subset, because the driver it does not know about is the one the
 * model added.
 *
 * `method` is `RULE_THRESHOLD` or `MODEL`, and the screen says which. A rule-derived class
 * shown as if a model produced it is the same lie the triage queue's `assisted` flag
 * exists to prevent, one screen further upstream.
 */
export const impactForecastSchema = z.object({
  id: z.string(),
  hazard_event_id: z.string(),
  gn_division_id: z.string(),
  gn_division_code: z.string(),
  generated_at: z.string(),
  valid_from: z.string(),
  valid_to: z.string(),
  impact_class: z.number().int().min(0).max(4),
  confidence: z.coerce.number(),
  lead_time_hours: z.number().int(),
  method: z.string(),
  model_version: z.string().nullable().default(null),
  drivers: z.record(z.string(), z.unknown()).default({}),
  expected_households_affected: z.number().int(),
  expected_road_access_loss: z.boolean(),
  correlation_id: z.string(),
});

export type ImpactForecast = z.infer<typeof impactForecastSchema>;

export const impactForecastListSchema = z.array(impactForecastSchema);

/**
 * A pre-agreed condition, and what happened when it fired.
 *
 * `condition` is data rather than code so it can be published and argued about in the
 * quiet years, which is the only time that argument is useful. A fired trigger always
 * names an action - a CHECK enforces it - so one that did nothing says `NO_ACTION` rather
 * than leaving the question open.
 */
export const anticipatoryTriggerSchema = z.object({
  id: z.string(),
  hazard_event_id: z.string(),
  gn_division_code: z.string().nullable().default(null),
  condition: z.record(z.string(), z.unknown()).default({}),
  fired_at: z.string().nullable().default(null),
  action_taken: z.string().nullable().default(null),
  forecast_id: z.string().nullable().default(null),
  notes: z.string().nullable().default(null),
  created_at: z.string(),
});

export type AnticipatoryTrigger = z.infer<typeof anticipatoryTriggerSchema>;

export const anticipatoryTriggerListSchema = z.array(anticipatoryTriggerSchema);

/** One role held by one user, within one administrative area. */
export const roleGrantSchema = z.object({
  grant_id: z.string(),
  role_code: z.string(),
  /**
   * Trilingual, and typed as such rather than as a loose record.
   *
   * `admin.role.name` carries the platform's `localised("name")` CHECK, so all three are
   * guaranteed by the database. Accepting a partial mapping here would let a two-language
   * name through and render `undefined` to readers of the third - which is the exact
   * failure the trilingual rule exists to prevent, in the screen that administers it.
   */
  role_name: z.object({ si: z.string(), ta: z.string(), en: z.string() }),
  scope_type: z.string(),
  scope_code: z.string(),
});

export type RoleGrant = z.infer<typeof roleGrantSchema>;

/**
 * An operator account and everything it can do.
 *
 * `mfa_enrolled` is on the row rather than behind a detail view because it is the question
 * the screen exists to answer during an incident: an approver with no second factor cannot
 * pass a gate, and finding that out when the gate refuses them is finding out too late.
 */
export const directoryUserSchema = z.object({
  id: z.string(),
  email: z.string().nullable().default(null),
  full_name: z.string().nullable().default(null),
  status: z.string(),
  last_login_at: z.string().nullable().default(null),
  created_at: z.string().nullable().default(null),
  mfa_enrolled: z.boolean().default(false),
  grants: z.array(roleGrantSchema).default([]),
  scopes: z.array(z.string()).default([]),
});

export type DirectoryUser = z.infer<typeof directoryUserSchema>;

export const directoryUserListSchema = z.array(directoryUserSchema);

/** A role and the scopes it carries, read from the code that enforces them. */
export const roleDefinitionSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.object({ si: z.string(), ta: z.string(), en: z.string() }),
  scopes: z.array(z.string()).default([]),
  grants_human_gate: z.boolean().default(false),
});

export type RoleDefinition = z.infer<typeof roleDefinitionSchema>;

export const roleDefinitionListSchema = z.array(roleDefinitionSchema);

/** The administrative scope levels `admin.user_role` accepts, and the code shape of each. */
export const SCOPE_TYPES = ['NATIONAL', 'DISTRICT', 'DS', 'GN'] as const;

export type ScopeType = (typeof SCOPE_TYPES)[number];

/**
 * What an alert would do, computed without sending anything.
 *
 * The mandatory step before a dispatch. A misconfigured area selection that targets all
 * 14,022 divisions has to be caught here, before twenty million messages - which is why
 * `exceeds_cap` is a field and not a comparison the console makes for itself.
 */
export const dryRunSchema = z.object({
  dry_run: z.literal(true),
  targeted: z.number().int(),
  by_channel: z.record(z.string(), z.number()),
  by_language: z.record(z.string(), z.number()),
  estimated_cost_lkr: z.coerce.number(),
  exceeds_cap: z.boolean(),
  cap: z.number().int(),
});

export type DryRun = z.infer<typeof dryRunSchema>;

/** What a real dispatch returns: the server's own sentence, never a bare percentage. */
export const dispatchResultSchema = z.object({
  dry_run: z.literal(false),
  alert_id: z.string(),
  summary: z.string(),
});

/**
 * A GN division from the hierarchy, for area selection.
 *
 * The code is the identity and the name is only a label: several divisions share a name,
 * and transliteration between the three scripts is not one-to-one. `GNDivisionPicker`
 * matches on the code and on all three names for the same reason.
 */
export const gnDivisionSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.record(z.string(), z.string()).default({}),
  ds_division_id: z.string(),
  population: z.number().int().default(0),
  household_count: z.number().int().default(0),
  /**
   * The division's centroid, for placing a boundary-free marker on the map.
   *
   * Used for the area-selection map and nowhere else. An *incident* is never placed at
   * its division centroid - that invents a precision the report does not have - but a
   * division legitimately has one, and it is what lets an operator pick an area by
   * clicking rather than by typing fourteen-character codes.
   */
  centroid_lon: z.coerce.number().nullable().default(null),
  centroid_lat: z.coerce.number().nullable().default(null),
});

export type GNDivisionRow = z.infer<typeof gnDivisionSchema>;

export const gnDivisionListSchema = z.array(gnDivisionSchema);

/**
 * One division boundary, as GeoJSON.
 *
 * `geometry` is nullable and stays nullable: seed boundaries below district level are
 * generated rectangles, and a division whose geometry was never loaded has none. Drawing
 * nothing for it is right; inventing a shape would put a boundary on a map that no survey
 * produced.
 */
export const divisionGeometrySchema = z.object({
  id: z.string(),
  code: z.string(),
  tolerance: z.coerce.number(),
  geometry: z.unknown().nullable().default(null),
});

export type DivisionGeometry = z.infer<typeof divisionGeometrySchema>;

/**
 * A household, with no personal data in it.
 *
 * `GET /admin/households` selects no name and no number, so there is nothing here to
 * redact - which is a stronger guarantee than redacting. The composition flags are the
 * vulnerability signals the triage and entitlement rules read, and they are what an
 * officer identifies a house by on this platform.
 */
export const householdSchema = z.object({
  id: z.string(),
  reference_code: z.string(),
  gn_division_id: z.string(),
  member_count: z.number().int(),
  has_over_70: z.boolean(),
  has_under_5: z.boolean(),
  has_mobility_impairment: z.boolean(),
  preferred_language: z.string(),
});

export type Household = z.infer<typeof householdSchema>;

export const householdListSchema = z.array(householdSchema);

/**
 * The damage categories `ledger-svc` accepts.
 *
 * Mirrors `sarana_shared.domain.taxonomy.DAMAGE_CATEGORIES`. A category this list has and
 * the service does not is a 400 on a filed assessment, so `tests/ledger` pins the two
 * together - the same cross-language vocabulary rule the incident types follow.
 */
export const DAMAGE_CATEGORIES = [
  'HOUSE_FULL',
  'HOUSE_PARTIAL',
  'HOUSEHOLD_GOODS',
  'LIVELIHOOD_TOOLS',
  'CROP',
  'LIVESTOCK',
  'FISHING_GEAR',
  'DEATH',
  'INJURY',
] as const;

export type DamageCategory = (typeof DAMAGE_CATEGORIES)[number];

/**
 * What `POST /assessments` returns.
 *
 * `duplicate` is not an error: a repeated `client_operation_id` returns the stored record,
 * because the device that retried did the right thing and should not have to interpret a
 * 409 to find that out.
 */
export const createdAssessmentSchema = z.object({
  id: z.string(),
  public_ref: z.string(),
  status: z.string(),
  duplicate: z.boolean().default(false),
});
