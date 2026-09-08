/**
 * The four citizen tabs.
 *
 * Four, in this order, and the order is the argument: the thing a person opens the app to
 * do at 2am is first, and the thing they open it to do three months later is last. Home
 * carries the warnings and the one dominant action; Aid carries the recovery experience.
 *
 * Labels, not icon-only. A tab bar of six pictograms is a puzzle for someone with low
 * literacy and a memory test for everyone else, and there is no version of this app where
 * a person should have to guess which tab holds their compensation.
 */

import { Tabs } from 'expo-router';
import { useColorScheme } from 'react-native';

import { useLocale } from '../../../src/providers/index.js';
import { SURFACES, fontScale, touchTarget, type } from '../../../src/theme/index.js';

export default function CitizenTabs() {
  const { t, locale } = useLocale();
  const surface = SURFACES[useColorScheme() === 'dark' ? 'dark' : 'light'];
  const label = type('xs', locale);

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: '#0E7C86',
        tabBarInactiveTintColor: surface.muted,
        tabBarStyle: {
          backgroundColor: surface.raised,
          borderTopColor: surface.divider,
          // Grows with the text setting. A fixed 49pt bar clips a Sinhala label at 150%.
          height: touchTarget('min') + label.lineHeight + 8,
          paddingBottom: 4,
        },
        tabBarLabelStyle: {
          fontSize: label.fontSize,
          lineHeight: label.lineHeight,
          fontFamily: label.fontFamily,
        },
        // The icon slot is deliberately empty: the label is the target, sized to be one.
        tabBarIconStyle: { display: 'none' },
        tabBarAllowFontScaling: false,
        tabBarItemStyle: { paddingVertical: 4 * fontScale() },
      }}
    >
      <Tabs.Screen name="home" options={{ title: t('tabs.home') }} />
      <Tabs.Screen name="report" options={{ title: t('tabs.report') }} />
      <Tabs.Screen name="status" options={{ title: t('tabs.status') }} />
      <Tabs.Screen name="aid" options={{ title: t('tabs.aid') }} />
    </Tabs>
  );
}
