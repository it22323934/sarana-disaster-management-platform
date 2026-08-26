/**
 * Zod schemas mirroring the Pydantic models in `sarana_shared.domain`.
 *
 * These are the runtime boundary: every payload that enters a web or mobile app is
 * parsed through one of them. The types the API client exposes are inferred from here,
 * so a server change that breaks a contract shows up as a parse failure with a field
 * name rather than as `undefined` three components deep.
 */

import { z } from 'zod';

/** UUIDv7 primary key. */
export const uuidSchema = z.string().uuid();

/** Correlation ID: the chain from citizen report to disbursement. */
export const correlationIdSchema = z.string().min(1).max(64);

/** ISO-8601 instant, always UTC on the wire. */
export const instantSchema = z.string().datetime({ offset: true });

/**
 * A citizen-facing string. All three locales required, none blank.
 *
 * Non-negotiable #2. There is no partial variant of this schema anywhere.
 */
export const localisedTextSchema = z.object({
  si: z.string().min(1),
  ta: z.string().min(1),
  en: z.string().min(1),
});
export type LocalisedTextPayload = z.infer<typeof localisedTextSchema>;

export const localeSchema = z.enum(['si', 'ta', 'en']);

/** Public short reference: `INC-260826-K3M9PQ`. Crockford base32, no I/L/O/U. */
export const shortCodeSchema = z.string().regex(/^[A-Z]{3}-\d{6}-[0-9A-HJKMNP-TV-Z]{6}$/);

export const districtCodeSchema = z.string().regex(/^LK-\d{2}$/);
export const dsCodeSchema = z.string().regex(/^LK-\d{2}-\d{2}$/);
export const gnCodeSchema = z.string().regex(/^LK-\d{2}-\d{2}-\d{3}$/);
export const adminCodeSchema = z.union([
  z.literal('LK'),
  z.string().regex(/^LK-P\d{2}$/),
  districtCodeSchema,
  dsCodeSchema,
  gnCodeSchema,
]);

/** How a coordinate was obtained. Drives how far the system trusts it. */
export const pointSourceSchema = z.enum(['gps', 'cell', 'manual', 'inferred']);

/**
 * A located observation in WGS 84, with provenance.
 *
 * `accuracyM` is required. A point with no accuracy is not trusted for dispatch, and
 * the type does not allow one to exist.
 */
export const geoPointSchema = z.object({
  lon: z.number().min(79).max(82.2),
  lat: z.number().min(5.7).max(10),
  accuracy_m: z.number().positive(),
  source: pointSourceSchema,
});
export type GeoPointPayload = z.infer<typeof geoPointSchema>;

/** NDRSC cost schedule revision, e.g. `2025.11` or `2025.11.2`. */
export const costScheduleVersionSchema = z.string().regex(/^\d{4}\.\d{2}(\.\d+)?$/);

/** An LKR amount bound to the schedule revision that produced it. */
export const moneySchema = z.object({
  cents: z.number().int(),
  cost_schedule_version: costScheduleVersionSchema,
});
export type MoneyPayload = z.infer<typeof moneySchema>;
