/**
 * Reading an exported queue back onto a device.
 *
 * `offline/export.ts` writes the file. This reads it, and the pair is the last-resort data
 * recovery path the brief asks for: "a file the officer can share via any channel if the
 * device is failing... saves weeks of work when it is needed."
 *
 * The realistic sequence is not pretty and it is what this is built for. A handset with a
 * failing screen or a dying battery, three weeks into a recovery, holding forty
 * assessments that have never synced. The officer exports the file, sends it over whatever
 * works — a memory card, a messaging app, an email from a district office computer — and it
 * is applied to a replacement handset.
 *
 * Three rules, and each is the difference between recovery and a second problem:
 *
 *   **Idempotent.** An operation already on the target is skipped, matched by
 *   `client_operation_id`. The officer will re-import the file: they will not be sure the
 *   first attempt worked, and a duplicate here is two payments against one household.
 *
 *   **Refuses a schema it cannot read.** A file from a newer build may carry fields this
 *   one would silently drop. Losing a field from a damage assessment quietly is worse than
 *   refusing and asking for the newer app.
 *
 *   **Reports rather than throws.** A file with one unreadable row still contains
 *   thirty-nine good ones, and a recovery path that gave up on the first bad row would
 *   discard the work it exists to save. The unreadable rows come back named.
 */

import { SCHEMA_VERSION } from '../offline/db/schema.js';
import type { Database } from '../offline/db/types.js';
import type { OperationLog } from '../offline/log/operation-log.js';
import { ENTITY_TYPES, type EntityType, type OperationVerb } from '../offline/log/types.js';
import type { QueueExport } from '../auth/logout.js';

export interface ImportedOperation {
  readonly client_operation_id: string;
  readonly seq: number;
  readonly entity_type: string;
  readonly op: string;
  readonly payload: unknown;
  readonly created_at?: string;
}

export interface ImportReport {
  /** Written to this device's log. */
  readonly applied: number;
  /** Already present, matched by client operation id. Re-importing is expected. */
  readonly skipped: number;
  /** Named, with the reason. Never silently dropped. */
  readonly refused: readonly { readonly clientOperationId: string; readonly reason: string }[];
  /** The device the file came from, so the screen can say whose work this is. */
  readonly sourceDeviceId: string;
}

export class QueueImportRefused extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'QueueImportRefused';
  }
}

/**
 * Whether a parsed object is an export file at all.
 *
 * Checked before anything is written, because the officer will pick the wrong file — a
 * photograph, last week's export, a log from a different app — and the message they get
 * decides whether they try again or give up.
 */
export function readExport(parsed: unknown): QueueExport {
  if (typeof parsed !== 'object' || parsed === null) {
    throw new QueueImportRefused('That file is not a SARANA queue export.');
  }

  const candidate = parsed as Partial<QueueExport>;
  if (typeof candidate.device_id !== 'string' || !Array.isArray(candidate.operations)) {
    throw new QueueImportRefused(
      'That file is not a SARANA queue export. Export again from the failing handset, ' +
        'through Sync then Export queue.',
    );
  }

  if (typeof candidate.schema_version !== 'number') {
    throw new QueueImportRefused('The export does not say which schema version wrote it.');
  }

  if (candidate.schema_version > SCHEMA_VERSION) {
    throw new QueueImportRefused(
      `The export was written by schema version ${candidate.schema_version} and this app ` +
        `reads up to ${SCHEMA_VERSION}. Update this handset before importing, or fields ` +
        'recorded on the other device would be dropped without saying so.',
    );
  }

  return candidate as QueueExport;
}

/**
 * Apply an export to this device.
 *
 * Every operation is appended with **its original `client_operation_id`**, which is what
 * makes the whole path safe: that id is the server's idempotency key, so if the failing
 * handset ever reaches a signal and syncs the same operation, the server stores one record
 * rather than two. The seq is reallocated by this device's log, because seq is a property
 * of a device's own sequence and two devices cannot share one.
 */
export async function importQueue(
  db: Database,
  log: OperationLog,
  file: QueueExport,
): Promise<ImportReport> {
  const refused: { clientOperationId: string; reason: string }[] = [];
  let applied = 0;
  let skipped = 0;

  // `QueueExport.operations` is typed as loose records, because the file may have been
  // written by a build that is not this one. Every field is checked below before it is
  // used, so the cast is narrowing a shape this function then validates rather than
  // asserting one it trusts.
  for (const operation of file.operations as readonly unknown[] as readonly ImportedOperation[]) {
    const id = operation?.client_operation_id;

    if (typeof id !== 'string' || id.length === 0) {
      refused.push({ clientOperationId: '(missing)', reason: 'the row has no operation id' });
      continue;
    }

    if (await log.byId(id)) {
      // Expected on a second import, and the reason the id is preserved rather than minted.
      skipped += 1;
      continue;
    }

    if (!(ENTITY_TYPES as readonly string[]).includes(operation.entity_type)) {
      refused.push({
        clientOperationId: id,
        reason: `'${operation.entity_type}' is not a kind of record this app syncs`,
      });
      continue;
    }

    if (operation.op !== 'create' && operation.op !== 'update') {
      refused.push({ clientOperationId: id, reason: `'${operation.op}' is not a known operation` });
      continue;
    }

    const payload = operation.payload;
    if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
      refused.push({ clientOperationId: id, reason: 'the payload is not a record' });
      continue;
    }

    if (isUnreadableMarker(payload)) {
      // **The exporter's own marker for a payload that would not parse.**
      //
      // It is an object, so the structural check above lets it through — which it did, and
      // a test caught it. Importing one would put `{ unreadable: true, raw: "..." }` into
      // the log as if it were an assessment, and the server would refuse it as a conflict
      // that jams the queue on the *replacement* handset. The recovery path would have
      // carried the failure across with the work.
      //
      // It cannot be sent and it cannot be repaired on a handset. Naming it is the most
      // this path can honestly do, and it is enough: the row is in the file, so somebody
      // with the file and a text editor can still see what was in it.
      refused.push({
        clientOperationId: id,
        reason: 'the payload could not be read on the device that wrote it',
      });
      continue;
    }

    await log.append({
      client_operation_id: id,
      entity_type: operation.entity_type as EntityType,
      entity_local_id: `imported_${id}`,
      op: operation.op as OperationVerb,
      payload: payload as Record<string, unknown>,
    });
    applied += 1;
  }

  return { applied, skipped, refused, sourceDeviceId: file.device_id };
}

/**
 * Whether a payload is the marker `exportQueue` writes for a row it could not parse.
 *
 * Kept as a named predicate beside the importer rather than inlined, because it is a
 * contract between two modules: `offline/export.ts` writes this shape and this file has to
 * recognise it. A change to one without the other reintroduces the bug where a corrupt row
 * is imported as though it were an assessment.
 */
function isUnreadableMarker(payload: object): boolean {
  return (payload as { unreadable?: unknown }).unreadable === true;
}
