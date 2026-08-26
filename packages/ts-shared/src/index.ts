/**
 * Shared TypeScript for every SARANA web and mobile surface.
 *
 * Subpath imports (`@sarana/ts-shared/i18n`) are preferred in application code; this
 * barrel exists for convenience in scripts and tests.
 */

export * from './api/index.js';
export * from './schemas/index.js';
export * from './i18n/index.js';
export * from './format/index.js';
