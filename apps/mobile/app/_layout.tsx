import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

/**
 * Root navigation.
 *
 * The app ships two surfaces from one binary: the citizen app (report a problem, see
 * alerts, file a grievance) and the Field Companion used by GN officers for damage
 * assessment. Which one a user sees is decided by their role at sign-in, not by
 * installing a different app - a GN officer is also a citizen.
 *
 * Both are offline-first: an append-only client operation log with idempotency keys and
 * server-authoritative merge (ADR-006), never a CRDT.
 */
export default function RootLayout() {
  return (
    <>
      <StatusBar style="auto" />
      <Stack screenOptions={{ headerShown: false }} />
    </>
  );
}
