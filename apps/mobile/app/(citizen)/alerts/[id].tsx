/**
 * One warning, in full.
 *
 * **The instruction is first and largest.** Not the headline, not the hazard type, not the
 * time it was issued - what to do. A person reading this at 2am has one question, and
 * putting the CAP instruction under a paragraph of context is how a warning gets read too
 * late.
 *
 * The whole screen renders from the device cache, so it works with no signal. That is not
 * a nicety: the network is worst exactly when a class 4 alert is in force.
 */

import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';

import { Button, Card, Heading, Screen, Text } from '../../../src/components/primitives.js';
import { body, headline, type CachedAlert } from '../../../src/citizen/cache.js';
import { useLocale, useOffline } from '../../../src/providers/index.js';

export default function AlertScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, locale } = useLocale();
  const { db } = useOffline();
  const router = useRouter();
  const [alert, setAlert] = useState<CachedAlert | null>(null);

  useEffect(() => {
    if (!db || !id) return;
    void db
      .select<CachedAlert>('SELECT * FROM alert_cache WHERE id = ?', [id])
      .then((rows) => setAlert(rows[0] ?? null));
    void db.execute('UPDATE alert_cache SET read_at = ? WHERE id = ? AND read_at IS NULL', [
      new Date().toISOString(),
      id,
    ]);
  }, [db, id]);

  if (!alert) return <Screen />;

  const expired = alert.effective_to !== null && Date.parse(alert.effective_to) < Date.now();

  return (
    <Screen>
      {/* Instruction first, at display size. Everything else is context for it. */}
      <Text size="sm" weight="medium" muted>
        {t('alert.instruction')}
      </Text>
      <Heading size="2xl">{body(alert, locale)}</Heading>

      <Card>
        <Text weight="medium">{headline(alert, locale)}</Text>
        <Text size="sm" muted>
          {t('alert.effective', { from: alert.effective_from.slice(0, 16).replace('T', ' ') })}
        </Text>
        {alert.effective_to ? (
          <Text size="sm" muted>
            {t('alert.expires', { to: alert.effective_to.slice(0, 16).replace('T', ' ') })}
          </Text>
        ) : null}
        {expired ? <Text size="sm">{t('alert.expired')}</Text> : null}
      </Card>

      <Card>
        <Text size="sm" muted>
          {t('alert.area')}
        </Text>
        {/* The GN division codes the alert targets. A map of them is the next step and
            needs the offline tile cache that file 24 builds; listing the codes is what can
            be shown truthfully today. */}
        <Text size="sm">{alert.area_codes.split(',').join(', ')}</Text>
      </Card>

      <Button label={t('shelter.title')} onPress={() => router.push('/(citizen)/shelters')} />
    </Screen>
  );
}
