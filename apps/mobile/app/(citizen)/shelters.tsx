/**
 * Shelters, from the device cache.
 *
 * Works offline, because the moment somebody needs this screen is the moment the cell
 * tower is congested. It asks for a position once, with an eight-second deadline, and
 * renders the list either way - a shelter list with no distances is far better than a
 * spinner.
 *
 * A full shelter is listed, not hidden. Sending a family to a building that turns them
 * away is worse than telling them it is full and showing them the next one.
 */

import * as Linking from 'expo-linking';
import { useEffect, useMemo, useState } from 'react';
import { View } from 'react-native';

import { Button, Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { shelterName, useCachedShelters } from '../../src/citizen/cache.js';
import { captureLocation } from '../../src/citizen/location.js';
import { nearestShelters, shelterCacheAge } from '../../src/citizen/shelters.js';
import type { ReportLocation } from '../../src/citizen/report-draft.js';
import { describeAge } from '../../src/offline/status/model.js';
import { useLocale, useOffline } from '../../src/providers/index.js';
import { SPACE } from '../../src/theme/index.js';

export default function SheltersScreen() {
  const { t, locale } = useLocale();
  const { db } = useOffline();
  const shelters = useCachedShelters(db);
  const [here, setHere] = useState<ReportLocation | null>(null);

  useEffect(() => {
    void captureLocation().then(setHere);
  }, []);

  const nearby = useMemo(
    () => nearestShelters(shelters, here, { limit: 10 }),
    [here, shelters],
  );
  const cacheAge = useMemo(() => shelterCacheAge(shelters, Date.now()), [shelters]);

  return (
    <Screen>
      <Heading>{t('shelter.title')}</Heading>

      {cacheAge?.stale ? (
        <Text size="sm" colour="#DC2626">
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

      {nearby.length === 0 ? (
        <Text muted>{t('shelter.none')}</Text>
      ) : (
        nearby.map((entry) => (
          <Card key={entry.shelter.id}>
            <Text weight="medium">{shelterName(entry.shelter, locale)}</Text>
            <View style={{ gap: SPACE[1] }}>
              <Text size="sm" muted>
                {entry.metres < 0
                  ? t('shelter.unranked')
                  : t('shelter.away', { metres: entry.metres })}
              </Text>
              <Text size="sm">
                {entry.hasSpace ? t('shelter.space') : t('shelter.full')}
                {' · '}
                {t('shelter.capacity', {
                  occupancy: entry.shelter.occupancy,
                  capacity: entry.shelter.capacity,
                })}
              </Text>
            </View>
            <Button
              label={t('shelter.directions')}
              variant="secondary"
              onPress={() => {
                // Handed to the platform's map app rather than drawn here: it has the road
                // network, and the straight-line distance above is honest about not having
                // one.
                void Linking.openURL(
                  `geo:${entry.shelter.latitude},${entry.shelter.longitude}?q=${entry.shelter.latitude},${entry.shelter.longitude}`,
                );
              }}
            />
          </Card>
        ))
      )}
    </Screen>
  );
}
