/**
 * Cursor pagination.
 *
 * Cursor, never offset. During a cyclone the incident list grows while an operator is
 * paging through it, and an offset silently skips or repeats rows exactly when someone
 * is trying to work out which reports have not been triaged yet.
 */

import { z } from 'zod';

export interface PageRequest {
  readonly cursor?: string;
  readonly limit?: number;
}

export const DEFAULT_PAGE_LIMIT = 50;
export const MAX_PAGE_LIMIT = 200;

export function pageSchema<T extends z.ZodTypeAny>(item: T) {
  return z.object({
    items: z.array(item),
    next_cursor: z.string().nullish(),
  });
}

export type Page<T> = {
  readonly items: readonly T[];
  readonly next_cursor?: string | null;
};

/** Turn a page request into query parameters, omitting defaults. */
export function pageParams(request: PageRequest = {}): Record<string, string> {
  const params: Record<string, string> = {};
  if (request.cursor) params.cursor = request.cursor;
  if (request.limit !== undefined) {
    if (!Number.isInteger(request.limit) || request.limit < 1 || request.limit > MAX_PAGE_LIMIT) {
      throw new RangeError(`limit must be an integer in 1..${MAX_PAGE_LIMIT}`);
    }
    params.limit = String(request.limit);
  }
  return params;
}
