/**
 * The typed reads behind every page. Server-only.
 *
 * One rule runs through this file and it is the difference between a transparency
 * dashboard and a marketing page:
 *
 * **A failed read renders as a stated failure, never as a zero.**
 *
 * `Result<T>` is either data or a reason. Nothing here throws into a page and nothing
 * substitutes an empty object, because both of those render as "Rs. 0 disbursed" — which
 * is not missing data, it is a specific and defamatory claim about a district that may
 * have disbursed a great deal. Every page checks the discriminant and shows the reason.
 *
 * The one exception is a genuine 404 on a district page, which `notFound()` handles: a
 * district code that does not exist is a wrong URL, not an outage.
 */

import 'server-only';

import {
  GEOMETRY_REVALIDATE_SECONDS,
  REVALIDATE_SECONDS,
  publicUrl,
  type PublicService,
} from './services';

export type Result<T> = { readonly ok: true; readonly data: T } | { readonly ok: false; readonly reason: FailureReason };

/**
 * Why a figure is missing, in the terms a reader needs rather than an HTTP status.
 *
 * `unreachable` and `refused` are separated because they mean different things to someone
 * deciding whether to quote the page: the first is our infrastructure and will pass, the
 * second means the service answered and said no, which is a bug worth reporting.
 */
export type FailureReason = 'unreachable' | 'refused' | 'malformed';

export interface FunnelStage {
  readonly lkr_cents: number;
  readonly count: number;
  readonly of_previous: number | null;
}

export interface PublicFunnel {
  readonly assessed: FunnelStage;
  readonly approved: FunnelStage;
  readonly disbursed: FunnelStage;
  readonly confirmed: FunnelStage;
  readonly unconfirmed_count: number;
  readonly awaiting_reply_count: number;
  readonly reversed_count: number;
  readonly reversed_lkr_cents: number;
  readonly households: number;
  readonly gn_divisions: number;
  readonly grievance_count: number;
  readonly grievance_open_count: number;
  readonly last_disbursement_at: string | null;
  readonly last_anchor_date: string | null;
  readonly last_seq: number | null;
  readonly as_of: string;
  readonly confirmation_window_days: number;
}

export interface DistrictMetrics {
  readonly district_code: string;
  readonly assessed_count: number;
  readonly assessed_households: number;
  readonly assessed_divisions: number;
  readonly assessed_lkr_cents: number;
  readonly approved_count: number;
  readonly approved_lkr_cents: number;
  readonly disbursed_count: number;
  readonly disbursed_lkr_cents: number;
  readonly confirmed_count: number;
  readonly reversed_count: number;
  readonly confirmation_rate: number | null;
  readonly median_days_to_disbursement: number | null;
  readonly disbursed_per_household_lkr_cents: number | null;
  readonly grievance_count: number;
  readonly grievance_open_count: number;
  readonly grievance_rate_per_1000_disbursements: number | null;
  readonly median_grievance_resolution_days: number | null;
  readonly last_released_at: string | null;
}

export interface DistrictMetricsResponse {
  readonly districts: readonly DistrictMetrics[];
  readonly as_of: string;
  readonly note: string;
}

export interface DSDivisionRow {
  readonly ds_division_code: string;
  readonly assessed_count: number;
  readonly assessed_households: number;
  readonly assessed_divisions: number;
  readonly assessed_lkr_cents: number;
  readonly approved_count: number;
  readonly approved_lkr_cents: number;
  readonly disbursed_count: number;
  readonly disbursed_lkr_cents: number;
  readonly confirmed_count: number;
  readonly median_days_to_disbursement: number | null;
}

export interface DistrictDetail {
  readonly district_code: string;
  readonly divisions: readonly DSDivisionRow[];
  readonly suppressed_divisions: number;
  readonly suppressed_disbursements: number;
  readonly suppressed_lkr_cents: number;
  readonly minimum_cell_size: number;
  readonly suppression_note: string;
  readonly totals: DSDivisionRow;
  readonly as_of: string;
}

export interface PublicLedgerEntry {
  readonly seq: number;
  readonly entitlement_id: string;
  readonly amount_lkr_cents: number;
  readonly released_by: string;
  readonly released_at: string;
  readonly payment_rail: string;
  readonly payment_ref: string | null;
  readonly prev_hash: string | null;
  readonly entry_hash: string | null;
  readonly reversed: boolean;
  readonly anchor_date: string;
}

export interface PublicLedgerResponse {
  readonly entries: readonly PublicLedgerEntry[];
  readonly next_seq: number | null;
  readonly scheme: Readonly<Record<string, string>>;
  readonly note: string;
}

export interface AnchorRow {
  readonly date: string;
  readonly merkle_root: string;
  readonly entry_count: number;
  readonly first_seq: number;
  readonly last_seq: number;
  readonly prev_anchor_hash: string | null;
  readonly s3_object_lock_uri: string | null;
  readonly published_at: string | null;
}

export interface AnchorResponse {
  readonly anchors: readonly AnchorRow[];
  readonly scheme: Readonly<Record<string, string>>;
}

export interface ScheduleLine {
  readonly id: string;
  readonly category: string;
  readonly subcategory: string;
  readonly description: Readonly<Record<string, string>>;
  readonly unit: string;
  readonly rate_lkr_cents: number;
  readonly cap_lkr_cents: number | null;
  readonly formula: Readonly<Record<string, unknown>>;
}

export interface CostSchedule {
  readonly id: string;
  readonly version: string;
  readonly published_at: string;
  readonly source_ref: string | null;
  readonly effective_from: string;
  readonly effective_to: string | null;
  readonly lines: readonly ScheduleLine[];
}

export interface GrievanceDistrict {
  readonly district_code: string;
  readonly total: number;
  readonly open_count: number;
  readonly closed_count: number;
  readonly breached_count: number;
  readonly median_resolution_seconds: number | null;
}

export interface GrievanceStats {
  readonly districts: readonly GrievanceDistrict[];
  readonly note: string;
}

export interface ConfirmationRate {
  readonly released: number;
  readonly confirmed: number;
  readonly unconfirmed: number;
  readonly awaiting_reply: number;
  readonly confirmation_rate: number | null;
  readonly window_days: number;
  readonly note: string;
}

export interface PublicAlert {
  readonly id: string;
  readonly cap_identifier: string;
  readonly headline: Readonly<Record<string, string>>;
  readonly description: Readonly<Record<string, string>>;
  readonly instruction: Readonly<Record<string, string>>;
  readonly severity: string;
  readonly urgency: string;
  readonly certainty: string;
  readonly status: string;
  readonly effective_at: string;
  readonly expires_at: string;
  readonly active: boolean;
  readonly gn_division_count: number;
  readonly targeted: number;
  readonly reached: number;
  readonly cap_xml_url: string;
}

export interface PublicAlertsResponse {
  readonly alerts: readonly PublicAlert[];
  readonly active_count: number;
  readonly as_of: string;
  readonly note: string;
}

export interface PublicAreaDistrict {
  readonly code: string;
  readonly name: Readonly<Record<string, string>>;
  readonly province_code: string;
  readonly province_name: Readonly<Record<string, string>>;
  readonly gn_division_count: number;
  readonly population: number;
  readonly household_count: number;
  readonly centroid_lon: number | null;
  readonly centroid_lat: number | null;
}

export interface PublicAreaDSDivision {
  readonly code: string;
  readonly name: Readonly<Record<string, string>>;
  readonly district_code: string;
  readonly gn_division_count: number;
  readonly population: number;
  readonly household_count: number;
}

export interface DistrictGeoJson {
  readonly type: 'FeatureCollection';
  readonly is_generated: boolean;
  readonly note: string;
  readonly features: readonly {
    readonly type: 'Feature';
    readonly id: string;
    readonly properties: { readonly district_code: string };
    readonly geometry: unknown;
  }[];
}

/**
 * How long a read may take before the page gives up on it.
 *
 * Eight seconds. Long enough for a cold Python service with a cold connection pool, short
 * enough that a hung upstream does not hold a request open until the ALB's own idle
 * timeout — at which point the reader gets a 504 with no explanation instead of a page
 * that says which figure is missing and why.
 */
const TIMEOUT_MS = 8_000;

async function read<T>(
  service: PublicService,
  path: string,
  revalidate: number = REVALIDATE_SECONDS,
): Promise<Result<T>> {
  try {
    const response = await fetch(publicUrl(service, path), {
      // No credentials, no cookies, no bearer token. These endpoints take none, and
      // sending one would be the first step towards a figure that is only public because
      // this app happens to hold an account.
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(TIMEOUT_MS),
      next: { revalidate },
    });

    if (!response.ok) return { ok: false, reason: 'refused' };
    return { ok: true, data: (await response.json()) as T };
  } catch (error) {
    // A JSON parse failure and a socket failure are different problems for whoever is
    // paged about them, so they are not collapsed. `SyntaxError` is what `.json()` throws.
    return { ok: false, reason: error instanceof SyntaxError ? 'malformed' : 'unreachable' };
  }
}

export const getFunnel = (): Promise<Result<PublicFunnel>> =>
  read<PublicFunnel>('ledger-svc', 'public/funnel');

export const getDistrictMetrics = (): Promise<Result<DistrictMetricsResponse>> =>
  read<DistrictMetricsResponse>('ledger-svc', 'public/districts');

export const getDistrictDetail = (code: string): Promise<Result<DistrictDetail>> =>
  read<DistrictDetail>('ledger-svc', `public/districts/${encodeURIComponent(code)}`);

export const getConfirmationRate = (): Promise<Result<ConfirmationRate>> =>
  read<ConfirmationRate>('ledger-svc', 'public/confirmation-rate');

export const getGrievanceStats = (): Promise<Result<GrievanceStats>> =>
  read<GrievanceStats>('ledger-svc', 'public/grievances');

export const getCostSchedules = (): Promise<Result<readonly CostSchedule[]>> =>
  read<readonly CostSchedule[]>('ledger-svc', 'cost-schedules');

export const getAnchors = (): Promise<Result<AnchorResponse>> =>
  read<AnchorResponse>('ledger-svc', 'ledger/anchors');

export const getLedgerPage = (fromSeq: number, limit: number): Promise<Result<PublicLedgerResponse>> =>
  read<PublicLedgerResponse>('ledger-svc', `ledger/public?from_seq=${fromSeq}&limit=${limit}`);

export const getAlerts = (): Promise<Result<PublicAlertsResponse>> =>
  read<PublicAlertsResponse>('alerting-svc', 'public/alerts?limit=100');

export const getAreaDistricts = (): Promise<Result<{ districts: readonly PublicAreaDistrict[] }>> =>
  read<{ districts: readonly PublicAreaDistrict[] }>(
    'core-api',
    'public/areas/districts',
    GEOMETRY_REVALIDATE_SECONDS,
  );

export const getAreaDSDivisions = (
  districtCode: string,
): Promise<Result<{ ds_divisions: readonly PublicAreaDSDivision[] }>> =>
  read<{ ds_divisions: readonly PublicAreaDSDivision[] }>(
    'core-api',
    `public/areas/ds-divisions?district_code=${encodeURIComponent(districtCode)}`,
    GEOMETRY_REVALIDATE_SECONDS,
  );

export const getDistrictGeoJson = (): Promise<Result<DistrictGeoJson>> =>
  read<DistrictGeoJson>(
    'core-api',
    'public/areas/districts.geojson',
    GEOMETRY_REVALIDATE_SECONDS,
  );

/**
 * Area codes to their trilingual names, or an empty map if the reference read failed.
 *
 * Empty rather than a failure, and this is the one place that substitution is right: a
 * missing *name* degrades a row from "Kandy" to "LK-21", which is still a correct and
 * usable answer. A missing *figure* would degrade to a wrong one, which is why nothing
 * else in this file does the same thing.
 */
export function nameIndex(
  areas: readonly { code: string; name: Readonly<Record<string, string>> }[],
): ReadonlyMap<string, Readonly<Record<string, string>>> {
  return new Map(areas.map((area) => [area.code, area.name]));
}
