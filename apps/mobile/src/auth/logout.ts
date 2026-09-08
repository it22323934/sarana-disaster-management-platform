/**
 * Signing out, and the case where the app refuses to.
 *
 * **Never log a user out while unsynced operations exist.** Signing out clears the
 * tokens and, on a shared handset, the database key with them - so a GN officer with
 * forty unsynced assessments who taps Sign out at the end of a shift would destroy a
 * day's fieldwork and get a login screen as confirmation.
 *
 * The refusal is not a warning the user can dismiss. It offers the two things that
 * actually resolve it: sync now, or export the queue to a file that can be handed to the
 * district office.
 */

export type LogoutVerdict =
  | { readonly allowed: true }
  | {
      readonly allowed: false;
      readonly reason: 'unsynced-work';
      readonly unsyncedCount: number;
      readonly attentionCount: number;
      readonly messageKey: string;
      readonly values: Readonly<Record<string, number>>;
      /** What the user may do instead. Both are real actions, not advice. */
      readonly offers: readonly ('sync-now' | 'export-queue' | 'force-sign-out')[];
    };

export interface LogoutRequest {
  readonly unsyncedCount: number;
  readonly attentionCount: number;
  /**
   * The user has read the warning, exported the queue and typed the confirmation.
   *
   * There has to be a way out: a device being handed to a different officer, or one whose
   * conflicts can only be resolved in the district office, cannot be locked to a session
   * forever. It is deliberately not a single tap.
   */
  readonly acknowledgedDataLoss?: boolean;
}

export function mayLogOut({
  unsyncedCount,
  attentionCount,
  acknowledgedDataLoss = false,
}: LogoutRequest): LogoutVerdict {
  if (unsyncedCount === 0) return { allowed: true };
  if (acknowledgedDataLoss) return { allowed: true };

  return {
    allowed: false,
    reason: 'unsynced-work',
    unsyncedCount,
    attentionCount,
    // Names the number. "You have unsaved changes" is the message that gets dismissed;
    // "40 assessments have not reached the server" is the one that does not.
    messageKey:
      attentionCount > 0 ? 'auth.logout.blockedWithAttention' : 'auth.logout.blocked',
    values: { count: unsyncedCount, attention: attentionCount },
    offers:
      attentionCount > 0
        ? ['sync-now', 'export-queue', 'force-sign-out']
        : ['sync-now', 'export-queue'],
  };
}

/**
 * What the export contains.
 *
 * Enough for the district office to replay the log against the server by hand, and
 * nothing more: the payloads are the operations the officer already wrote, and the file
 * carries no token, no key and no session.
 */
export interface QueueExport {
  readonly exported_at: string;
  readonly device_id: string;
  readonly server_cursor: number;
  readonly schema_version: number;
  readonly operations: readonly Record<string, unknown>[];
  readonly note: string;
}

export const EXPORT_NOTE =
  'Operations this device has not confirmed with the server. Replay them with ' +
  'POST /api/v1/assessments/sync using the same client_operation_id values - the keys are ' +
  'what make a replay safe. This file contains no credentials.';
