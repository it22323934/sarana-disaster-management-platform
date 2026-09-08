/**
 * The Field Companion.
 *
 * GN officers only, and gated on the role rather than on the scope: a DS approver
 * reviews assessments and does not file them, and giving them the form would put their
 * name on a record the segregation rule at release time then refuses.
 *
 * The screens land in file 24.
 */

import { Redirect, Stack } from 'expo-router';

import { mayEnter } from '../../src/auth/session.js';
import { useSession } from '../../src/providers/index.js';

export default function FieldLayout() {
  const { session } = useSession();

  if (!session) return <Redirect href="/sign-in" />;
  // Checked on every entry, not only at sign-in. A role revoked mid-shift takes effect
  // the next time the officer navigates, rather than at the next cold start.
  if (!mayEnter(session, 'field')) return <Redirect href="/(citizen)" />;

  return <Stack screenOptions={{ headerShown: false }} />;
}
