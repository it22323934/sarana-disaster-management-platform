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
 *
 * The status strip is mounted here, outside the navigator, so it is on every screen in
 * both surfaces and cannot be scrolled away. It is the one component a field officer has
 * to be able to find without looking for it.
 */

import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View, useColorScheme } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { SyncStatusStrip } from '../src/components/SyncStatusStrip.js';
import { AppProviders, useLocale, useOffline } from '../src/providers/index.js';
import { SURFACES } from '../src/theme/index.js';

function Shell() {
  const { ready: localeReady } = useLocale();
  const { failure } = useOffline();
  const scheme = useColorScheme() === 'dark' ? 'dark' : 'light';
  const surface = SURFACES[scheme];

  // Nothing renders text before the stored locale has been read. A frame of English on a
  // Tamil speaker's phone is a small thing that undoes a large promise.
  if (!localeReady) return <View style={{ flex: 1, backgroundColor: surface.base }} />;

  return (
    <View style={{ flex: 1, backgroundColor: surface.base }}>
      <Stack screenOptions={{ headerShown: false }} />
      {failure === null ? <SyncStatusStrip /> : null}
    </View>
  );
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <StatusBar style="auto" />
      <AppProviders>
        <Shell />
      </AppProviders>
    </SafeAreaProvider>
  );
}
