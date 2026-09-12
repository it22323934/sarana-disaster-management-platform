/**
 * Which of the two surfaces a signed-in user sees.
 *
 * One binary, two experiences: the Citizen app and the Field Companion. Which one a user
 * gets is decided by their role at sign-in, not by installing a different app - a GN
 * officer is also a citizen, and during a flood they are a citizen first.
 *
 * The role names are `sarana_shared.auth.scopes.Role`. They are literals here because the
 * two languages cannot share a module; `test/role-vocabulary.test.ts` checks them against
 * the Python enum so a rename fails a test rather than a sign-in.
 */

export const ROLES = [
  'CITIZEN',
  'GN_OFFICER',
  'DS_APPROVER',
  'DISTRICT_APPROVER',
  'DMC_OPERATOR',
  'DISPATCHER',
  'AUDITOR',
  'ADMIN',
  // Machine principals. Neither ever signs in on a handset; they are listed because the
  // vocabulary has to match the server's exactly, not because the app has a use for them.
  'AGENT',
  'SERVICE',
] as const;

export type Role = (typeof ROLES)[number];

export type Surface = 'citizen' | 'field';

export interface Session {
  readonly subjectId: string;
  readonly roles: readonly Role[];
  readonly displayName: string | null;
  /** The GN division a field officer is assigned to. Null for everyone else. */
  readonly gnDivisionCode: string | null;
  /**
   * The household this person's aid records belong to, if they have linked one.
   *
   * Null is the normal state and not an error: linking is optional, it is skipped at
   * onboarding by most people, and a citizen who never links still gets warnings and can
   * still report. The Aid tab is the only surface that needs it, and it says so rather
   * than rendering an empty screen.
   */
  readonly householdId: string | null;
}

/**
 * Only a GN officer gets the Field Companion.
 *
 * Deliberately narrower than "anyone who can write an assessment". A DS approver reviews
 * assessments and does not file them, and giving them a form they are not meant to use
 * would put their name on a record the segregation rule at release time then refuses.
 */
export function surfacesFor(session: Session): readonly Surface[] {
  const surfaces: Surface[] = ['citizen'];
  if (session.roles.includes('GN_OFFICER')) surfaces.push('field');
  return surfaces;
}

/**
 * Where to send a user who has just signed in.
 *
 * A GN officer lands in the Field Companion, because that is what they opened the app to
 * do on a working day. They can switch, and the switch is one tap and always visible -
 * an officer whose own house is flooding must not have to sign out to report it.
 */
export function landingSurface(session: Session): Surface {
  return surfacesFor(session).includes('field') ? 'field' : 'citizen';
}

/** Whether a user may reach a surface at all. Checked on every route, not only at login. */
export function mayEnter(session: Session, surface: Surface): boolean {
  return surfacesFor(session).includes(surface);
}
