/**
 * The entry point, which decides where a user actually starts.
 *
 * Three branches, in this order:
 *
 *   1. The device database would not open. Fatal, and stated - an app that silently fell
 *      back to memory would lose a day's fieldwork without ever saying so.
 *   2. The language has never been chosen and the device locale is not one SARANA
 *      speaks. The picker goes in front of them rather than defaulting silently.
 *   3. Otherwise, the surface their role earns them.
 *
 * There is no "loading" screen with a spinner. Opening a local SQLite file takes
 * milliseconds, and the honest thing to show for milliseconds is the background colour.
 */

import { Redirect } from 'expo-router';
import { View, useColorScheme } from 'react-native';

import { Card, Screen, Text, Heading } from '../src/components/primitives.js';
import { useLocale, useOffline, useSession } from '../src/providers/index.js';
import { SURFACES } from '../src/theme/index.js';

export default function Index() {
  const { promptForLocale, t } = useLocale();
  const { ready, failure } = useOffline();
  const { session, surface } = useSession();
  const scheme = useColorScheme() === 'dark' ? 'dark' : 'light';

  if (failure !== null) {
    return (
      <Screen>
        <Heading>{t('app.name')}</Heading>
        <Card>
          <Text weight="medium">This device&apos;s secure database could not be opened.</Text>
          <Text muted size="sm">
            Nothing has been lost - the data is still on the device, encrypted. Report this
            to the district office rather than reinstalling: a reinstall discards the
            encryption key and everything it protects.
          </Text>
          <Text muted size="xs">
            {failure}
          </Text>
        </Card>
      </Screen>
    );
  }

  if (promptForLocale) return <Redirect href="/language" />;
  if (!ready) return <View style={{ flex: 1, backgroundColor: SURFACES[scheme].base }} />;
  if (!session) return <Redirect href="/sign-in" />;

  return <Redirect href={surface === 'field' ? '/(field)' : '/(citizen)/(tabs)/home'} />;
}
