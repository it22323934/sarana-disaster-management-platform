'use client';

/**
 * The console's data layer.
 *
 * **On polling.** File 20 specifies SSE from core-api. There is no SSE endpoint on
 * core-api — no service in the platform emits `text/event-stream` today — so everything
 * here polls, and `LIVE_INTERVAL_MS` is the one place that changes when a stream exists.
 * The pending-gate count polls regardless: the brief calls for a belt-and-braces poll on
 * that number even with SSE working, because it is the number that must never be stale.
 *
 * Poll intervals are chosen against what the number costs if it is wrong, not against
 * what feels responsive:
 *
 *   gates      5s   an approval waiting unseen is the failure this console exists to stop
 *   queue     15s   ordering shifts as reports arrive; a 15s-old queue is still actionable
 *   reference 5min  divisions and responders barely change during an incident
 */

import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import type { z } from 'zod';

import { gatewayFetch } from './gateway-client';
import {
  PENDING_PLAN_STATUSES,
  alertListSchema,
  alertTemplateListSchema,
  anchorResponseSchema,
  anomalyListSchema,
  assessmentListSchema,
  auditEntryListSchema,
  costScheduleListSchema,
  dispatchPlanListSchema,
  dispatchPlanSchema,
  disbursementListSchema,
  entitlementSchema,
  grievanceListSchema,
  deliverySchema,
  gapListSchema,
  incidentListSchema,
  incidentSchema,
  ledgerListSchema,
  queueSchema,
  responderListSchema,
  reviewListSchema,
  verifySchema,
  type Alert,
  type AlertTemplate,
  type Anomaly,
  type Assessment,
  type AuditEntry,
  type CostSchedule,
  type Delivery,
  type DispatchPlan,
  type Entitlement,
  type Gap,
  type Grievance,
  type Incident,
  type LedgerEntry,
  type Queue,
  type Responder,
  type ReviewItem,
  type VerifyResult,
} from './schemas';

export const GATE_INTERVAL_MS = 5_000;
export const LIVE_INTERVAL_MS = 15_000;
export const REFERENCE_INTERVAL_MS = 300_000;

export const queryKeys = {
  pendingPlans: ['dispatch-plans', 'pending'] as const,
  plan: (id: string) => ['dispatch-plans', id] as const,
  queue: (divisionCode?: string) => ['incidents', 'queue', divisionCode ?? 'all'] as const,
  incidents: (ids: readonly string[]) => ['incidents', 'by-id', [...ids].sort()] as const,
  responders: ['responders'] as const,
  entitlement: (id: string) => ['entitlements', id] as const,
  disbursements: ['disbursements'] as const,
  grievances: (entitlementId: string) => ['grievances', entitlementId] as const,
  anomalies: (divisionCode?: string) => ['anomalies', divisionCode ?? 'all'] as const,
  incident: (id: string) => ['incidents', id] as const,
  incidentList: (status?: string) => ['incidents', 'list', status ?? 'all'] as const,
  alerts: (status?: string) => ['alerts', status ?? 'all'] as const,
  delivery: (alertId: string) => ['alerts', alertId, 'delivery'] as const,
  gaps: (alertId: string) => ['alerts', alertId, 'gaps'] as const,
  ledger: (fromSeq: number) => ['ledger', fromSeq] as const,
  reviewQueue: ['review-queue'] as const,
  templates: ['templates'] as const,
  anchors: ['ledger', 'anchors'] as const,
  costSchedules: ['cost-schedules'] as const,
  auditFor: (subjectType: string, subjectId: string) =>
    ['audit', subjectType, subjectId] as const,
  assessments: (division?: string) => ['assessments', division ?? 'all'] as const,
  grievanceList: (status?: string) => ['grievances', 'list', status ?? 'all'] as const,
};

/**
 * Dispatch plans a human still has to decide.
 *
 * Fetched per status and merged rather than fetched unfiltered and filtered here: an
 * unfiltered list during a national event is thousands of rows, and the banner needs a
 * count every five seconds.
 */
export function usePendingPlans(): UseQueryResult<DispatchPlan[]> {
  return useQuery({
    queryKey: queryKeys.pendingPlans,
    refetchInterval: GATE_INTERVAL_MS,
    // Keep polling when the tab is in the background. An operator with the console on a
    // second monitor is the normal case, and a banner that froze when it lost focus would
    // be worse than no banner.
    refetchIntervalInBackground: true,
    queryFn: async () => {
      const pages = await Promise.all(
        PENDING_PLAN_STATUSES.map((status) =>
          gatewayFetch('dispatch-plans', {
            query: { status, limit: 500 },
            schema: dispatchPlanListSchema,
          }),
        ),
      );
      return pages
        .flat()
        .sort((a, b) => a.proposed_at.localeCompare(b.proposed_at));
    },
  });
}

export function usePlan(planId: string): UseQueryResult<DispatchPlan> {
  return useQuery({
    queryKey: queryKeys.plan(planId),
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () => gatewayFetch(`dispatch-plans/${planId}`, { schema: dispatchPlanSchema }),
  });
}

export function useTriageQueue(divisionCode?: string): UseQueryResult<Queue> {
  return useQuery({
    queryKey: queryKeys.queue(divisionCode),
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () =>
      gatewayFetch('incidents/queue', {
        query: { gn_division_code: divisionCode, limit: 200 },
        schema: queueSchema,
      }),
  });
}

/**
 * The incidents a plan covers.
 *
 * One request per id. `incident-svc` has no bulk-by-id read, and a plan covers a handful
 * of incidents rather than hundreds, so the alternative — listing everything and filtering
 * client-side — would be far more expensive on the one screen that has to load fast.
 */
export function usePlanIncidents(ids: readonly string[]): UseQueryResult<Incident[]> {
  return useQuery({
    queryKey: queryKeys.incidents(ids),
    enabled: ids.length > 0,
    queryFn: async () => {
      const rows = await Promise.all(
        ids.map((id) =>
          gatewayFetch(`incidents/${id}`, { schema: incidentListSchema.element }),
        ),
      );
      // Highest severity first, then most people at risk. The dispatcher reads the top of
      // this list under time pressure, so it leads with what the decision turns on.
      return rows.sort(
        (a, b) => b.severity - a.severity || b.people_at_risk - a.people_at_risk,
      );
    },
  });
}

export function useResponders(): UseQueryResult<Responder[]> {
  return useQuery({
    queryKey: queryKeys.responders,
    refetchInterval: REFERENCE_INTERVAL_MS,
    queryFn: () => gatewayFetch('responders', { schema: responderListSchema }),
  });
}

export function useEntitlement(id: string): UseQueryResult<Entitlement> {
  return useQuery({
    queryKey: queryKeys.entitlement(id),
    queryFn: () => gatewayFetch(`entitlements/${id}`, { schema: entitlementSchema }),
  });
}

export function useDisbursements(): UseQueryResult<ReturnType<typeof Array.prototype.slice>> {
  return useQuery({
    queryKey: queryKeys.disbursements,
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () => gatewayFetch('disbursements', { schema: disbursementListSchema }),
  });
}

/**
 * Grievances on one entitlement.
 *
 * An open one blocks the release, and `ledger-svc` refuses it server-side. The console
 * fetches them so the approver sees *why* before they press the button, rather than
 * pressing it and receiving a 409.
 */
export function useGrievances(entitlementId: string): UseQueryResult<Grievance[]> {
  return useQuery({
    queryKey: queryKeys.grievances(entitlementId),
    enabled: entitlementId.length > 0,
    queryFn: () =>
      gatewayFetch('grievances', {
        query: { entitlement_id: entitlementId },
        schema: grievanceListSchema,
      }),
  });
}

export function useAnomalies(divisionCode?: string): UseQueryResult<Anomaly[]> {
  return useQuery({
    queryKey: queryKeys.anomalies(divisionCode),
    queryFn: () =>
      gatewayFetch('anomalies', {
        query: { gn_division_code: divisionCode },
        schema: anomalyListSchema,
      }),
  });
}

export function useIncident(id: string): UseQueryResult<Incident> {
  return useQuery({
    queryKey: queryKeys.incident(id),
    enabled: id.length > 0,
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () => gatewayFetch(`incidents/${id}`, { schema: incidentSchema }),
  });
}

export function useIncidents(status?: string): UseQueryResult<Incident[]> {
  return useQuery({
    queryKey: queryKeys.incidentList(status),
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () =>
      gatewayFetch('incidents', {
        query: { status, limit: 200 },
        schema: incidentListSchema,
      }),
  });
}

export function useAlerts(status?: string): UseQueryResult<Alert[]> {
  return useQuery({
    queryKey: queryKeys.alerts(status),
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () =>
      gatewayFetch('alerts', { query: { status, limit: 200 }, schema: alertListSchema }),
  });
}

export function useDelivery(alertId: string): UseQueryResult<Delivery> {
  return useQuery({
    queryKey: queryKeys.delivery(alertId),
    enabled: alertId.length > 0,
    // Faster than the reference interval: delivery receipts arrive over minutes, and an
    // operator watching a dispatch land wants the confirmed count to move.
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () => gatewayFetch(`alerts/${alertId}/delivery`, { schema: deliverySchema }),
  });
}

/**
 * The divisions that probably did not get the warning.
 *
 * Ordered worst-first by the server, and the console does not re-sort it. This is the
 * screen that turns "we sent the warning" into "these 14 divisions probably did not get
 * it, send a vehicle", and the order is the instruction.
 */
export function useDeliveryGaps(alertId: string): UseQueryResult<Gap[]> {
  return useQuery({
    queryKey: queryKeys.gaps(alertId),
    enabled: alertId.length > 0,
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () => gatewayFetch(`alerts/${alertId}/delivery/gaps`, { schema: gapListSchema }),
  });
}

/**
 * Every template, published or not.
 *
 * Unfiltered on purpose. The composer offers only `PUBLISHED` ones, but it lists the rest
 * with the reason they are unavailable: an operator who cannot find the flood template
 * needs to know it is awaiting a Tamil signature, not that it does not exist.
 */
export function useTemplates(): UseQueryResult<AlertTemplate[]> {
  return useQuery({
    queryKey: queryKeys.templates,
    refetchInterval: REFERENCE_INTERVAL_MS,
    queryFn: () =>
      gatewayFetch('templates', { query: { limit: 200 }, schema: alertTemplateListSchema }),
  });
}

export function useLedger(fromSeq = 0): UseQueryResult<LedgerEntry[]> {
  return useQuery({
    queryKey: queryKeys.ledger(fromSeq),
    queryFn: () =>
      gatewayFetch('ledger', { query: { from_seq: fromSeq, limit: 200 }, schema: ledgerListSchema }),
  });
}

export function useReviewQueue(): UseQueryResult<ReviewItem[]> {
  return useQuery({
    queryKey: queryKeys.reviewQueue,
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () => gatewayFetch('review-queue', { schema: reviewListSchema }),
  });
}

export function useGrievanceList(status?: string): UseQueryResult<Grievance[]> {
  return useQuery({
    queryKey: queryKeys.grievanceList(status),
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () =>
      gatewayFetch('grievances', { query: { status, limit: 200 }, schema: grievanceListSchema }),
  });
}

/**
 * Every cost schedule version, with every line and its published formula.
 *
 * Reference data in the strongest sense: a schedule is what every entitlement in the
 * system is calculated from, and versions are added by migration rather than from a
 * console. Polled at the reference interval because it effectively never changes.
 */
/**
 * Everything recorded against one subject, oldest first.
 *
 * Ordered rather than sorted by recency, because the order *is* the content: an approval
 * that came after a disbursement is a finding, and it is only visible if the sequence is
 * preserved. `seq` is the authority on that, not the timestamp - two actions in the same
 * millisecond still have an order.
 */
export function useAuditTrail(
  subjectType: string,
  subjectId: string,
): UseQueryResult<AuditEntry[]> {
  return useQuery({
    queryKey: queryKeys.auditFor(subjectType, subjectId),
    enabled: subjectId.length > 0,
    queryFn: async () => {
      const rows = await gatewayFetch('audit', {
        query: { subject_type: subjectType, subject_id: subjectId, limit: 100 },
        schema: auditEntryListSchema,
      });
      return [...rows].sort((a, b) => a.seq - b.seq);
    },
  });
}

export function useCostSchedules(): UseQueryResult<CostSchedule[]> {
  return useQuery({
    queryKey: queryKeys.costSchedules,
    refetchInterval: REFERENCE_INTERVAL_MS,
    queryFn: () => gatewayFetch('cost-schedules', { schema: costScheduleListSchema }),
  });
}

export function useAnchors(): UseQueryResult<z.infer<typeof anchorResponseSchema>> {
  return useQuery({
    queryKey: queryKeys.anchors,
    refetchInterval: REFERENCE_INTERVAL_MS,
    queryFn: () =>
      gatewayFetch('ledger/anchors', { query: { limit: 400 }, schema: anchorResponseSchema }),
  });
}

export function useAssessments(division?: string): UseQueryResult<Assessment[]> {
  return useQuery({
    queryKey: queryKeys.assessments(division),
    refetchInterval: LIVE_INTERVAL_MS,
    queryFn: () =>
      gatewayFetch('assessments', {
        query: { division, limit: 200 },
        schema: assessmentListSchema,
      }),
  });
}

/**
 * Recompute the hash chain over a range.
 *
 * Deliberately **not** a `useQuery`. Verification is an action an auditor takes and reads
 * the result of, not something a page does on its own: a range that silently re-verified
 * every fifteen seconds would turn a deliberate check into background noise, and the
 * answer would scroll past unread.
 */
export async function verifyChain(fromSeq?: number, toSeq?: number): Promise<VerifyResult> {
  return gatewayFetch('audit/verify', {
    query: { from_seq: fromSeq, to_seq: toSeq },
    schema: verifySchema,
  });
}

/** Invalidate everything a gate decision changes. Called after approve, reject, release. */
export function useInvalidateGates(): () => Promise<void> {
  const client = useQueryClient();
  return async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: queryKeys.pendingPlans }),
      client.invalidateQueries({ queryKey: ['dispatch-plans'] }),
      client.invalidateQueries({ queryKey: queryKeys.disbursements }),
      client.invalidateQueries({ queryKey: ['incidents'] }),
    ]);
  };
}
