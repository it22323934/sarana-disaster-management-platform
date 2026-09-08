/**
 * The citizen surface.
 *
 * Report a problem, read warnings for your area, track a grievance. Everyone who signs in
 * reaches it, including GN officers - during a flood an officer is a citizen first, and
 * having to sign out to report their own house would be indefensible.
 *
 * A stack over a tab group rather than tabs at the root: the report flow, an alert and the
 * entitlement working are all full-screen and push over the tabs. Someone filling in a
 * report under stress should not be one mis-tap from the aid screen.
 */

import { Redirect, Stack } from 'expo-router';

import { useSession } from '../../src/providers/index.js';

export default function CitizenLayout() {
  const { session } = useSession();
  if (!session) return <Redirect href="/sign-in" />;

  return <Stack screenOptions={{ headerShown: false }} />;
}
