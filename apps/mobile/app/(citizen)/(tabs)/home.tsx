/**
 * The home screen, designed for 2am.
 *
 * One obviously dominant action, and everything else visually quieter. This is not a
 * dashboard: a person whose house is flooding does not need a summary of the situation,
 * they need the button.
 *
 * The order down the screen is the order of urgency, not the order of importance to the
 * platform. Active warnings first, because they may say evacuate and the person may not
 * know yet. Then the SOS. Then the nearest shelter, which is what they need after they
 * have reported. Nothing else.
 */

import { useRouter } from 'expo-router';
import { useMemo } from 'react';
import { Pressable, StyleSheet, View, useColorScheme } from 'react-native';

import { Card, Screen, Text, useSurface } from '../../../src/components/primitives.js';
import { nearestShelters, shelterCacheAge } from '../../../src/citizen/shelters.js';
import { describeAge } from '../../../src/offline/status/model.js';
import { useLocale, useOffline } from '../../../src/providers/index.js';
import { RADIUS, SPACE, fontScale, touchTarget, type } from '../../../src/theme/index.js';
import { body, headline, shelterName, useCachedAlerts, useCachedShelters } from '../../../src/citizen/cache.js';

export default function CitizenHome() {
  const { t, locale } = useLocale();
  const { db } = useOffline();
  const surface = useSurface();
  const scheme = useColorScheme() === 'dark' ? 'dark' : 'light';
  const router = useRouter();

  const alerts = useCachedAlerts(db);
  const shelters = useCachedShelters(db);

  // No position yet: the home screen does not ask for GPS just to rank a shelter list.
  // Location is requested when a report starts, which is the moment it is justified.
  const nearest = useMemo(() => nearestShelters(shelters, null, { limit: 1 })[0] ?? null, [shelters]);
  const cacheAge = useMemo(() => shelterCacheAge(shelters, Date.now()), [shelters]);

  // 56 is the design system's SOS floor and this is well past it. The button is the
  // screen: at 200% text on a small handset it still fills the middle third.
  const sosSize = Math.max(touchTarget('sos') * 2.4, 160 * fontScale());

  return (
    <Screen>
      {alerts.length > 0 ? (
        <View style={{ gap: SPACE[2] }}>
          <Text size="sm" weight="medium">
            {t('home.activeAlerts', { count: alerts.length })}
          </Text>
          {alerts.map((alert) => (
            <Pressable
              key={alert.id}
              onPress={() => router.push(`/(citizen)/alerts/${alert.id}`)}
              accessibilityRole="button"
              style={[
                styles.alert,
                {
                  // Severity colour is one signal; the instruction being first and largest
                  // is the other. A colour-blind reader loses nothing.
                  backgroundColor: alert.severity >= 3 ? '#7F1D1D' : surface.card,
                  borderColor: alert.severity >= 3 ? '#7F1D1D' : surface.divider,
                  minHeight: touchTarget('min'),
                },
              ]}
            >
              <Text
                size="lg"
                weight="semibold"
                colour={alert.severity >= 3 ? '#FFECEC' : surface.text}
              >
                {headline(alert, locale)}
              </Text>
              <Text size="sm" colour={alert.severity >= 3 ? '#FFECEC' : surface.muted}>
                {body(alert, locale)}
              </Text>
            </Pressable>
          ))}
        </View>
      ) : (
        <Text size="sm" muted>
          {t('home.noAlerts')}
        </Text>
      )}

      <View style={styles.sosWrap}>
        <Pressable
          onPress={() => router.push('/(citizen)/report/new')}
          accessibilityRole="button"
          accessibilityLabel={t('home.sos')}
          accessibilityHint={t('home.sosHint')}
          style={({ pressed }) => [
            styles.sos,
            {
              width: sosSize,
              height: sosSize,
              borderRadius: sosSize / 2,
              backgroundColor: pressed ? '#5F1616' : '#7F1D1D',
            },
          ]}
        >
          <Text
            colour="#FFECEC"
            weight="semibold"
            align="center"
            size="lg"
            style={{ paddingHorizontal: SPACE[4] }}
          >
            {t('home.sos')}
          </Text>
        </Pressable>
        <Text size="xs" muted align="center">
          {t('home.sosHint')}
        </Text>
      </View>

      <Pressable onPress={() => router.push('/(citizen)/shelters')} accessibilityRole="button">
        <Card>
          <Text size="sm" weight="medium">
            {t('home.nearestShelter')}
          </Text>
          {nearest === null ? (
            <Text size="sm" muted>
              {t('shelter.none')}
            </Text>
          ) : (
            <>
              <Text>{shelterName(nearest.shelter, locale)}</Text>
              <Text size="sm" muted>
                {nearest.metres < 0
                  ? t('shelter.unranked')
                  : t('shelter.away', { metres: nearest.metres })}
                {' · '}
                {nearest.hasSpace ? t('shelter.space') : t('shelter.full')}
              </Text>
            </>
          )}
          {cacheAge?.stale ? (
            <Text size="xs" colour={scheme === 'dark' ? '#DB8118' : '#9E5604'}>
              {t('shelter.stale')}
            </Text>
          ) : cacheAge ? (
            <Text size="xs" muted>
              {t('shelter.cached', {
                age: t(`time.age.${describeAge(cacheAge.ageMs).key}`, {
                  age: describeAge(cacheAge.ageMs).value,
                }),
              })}
            </Text>
          ) : null}
        </Card>
      </Pressable>
    </Screen>
  );
}

const styles = StyleSheet.create({
  alert: { gap: SPACE[1], padding: SPACE[3], borderRadius: RADIUS.surface, borderWidth: 1 },
  sosWrap: { alignItems: 'center', gap: SPACE[3], paddingVertical: SPACE[4] },
  sos: { alignItems: 'center', justifyContent: 'center' },
});
