/**
 * The Field Companion home.
 *
 * A shell in file 22. The assessment form, the household list and the offline map are
 * file 24. The offline permit is shown here because it is the credential the whole
 * surface depends on, and an officer needs to know it is valid *before* they walk into a
 * division with no signal - not when a sync fails three days later.
 */

import { useRouter } from 'expo-router';

import { capabilityStatus } from '../../src/auth/capability.js';
import { Button, Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { useLocale, useOffline, useSession } from '../../src/providers/index.js';

export default function FieldHome() {
  const { t } = useLocale();
  const { counts } = useOffline();
  const { session, capability, setSurface } = useSession();
  const router = useRouter();

  const division = session?.gnDivisionCode ?? '';
  const status = capabilityStatus(capability, { division, now: Date.now() });

  return (
    <Screen>
      <Heading>{t('app.name')}</Heading>

      <Card>
        <Text weight="semibold">{t('auth.capability.title')}</Text>
        {status.usable ? (
          <Text size="sm">
            {t('auth.capability.held', {
              hours: Math.floor(status.expiresInMs / 3_600_000),
              division,
            })}
          </Text>
        ) : (
          <Text size="sm">
            {status.reason === 'expired'
              ? t('auth.capability.expired')
              : status.reason === 'wrong-division'
                ? t('auth.capability.wrongDivision', {
                    held: capability?.gnDivisionCode ?? '',
                    asked: division,
                  })
                : t('auth.capability.absent')}
          </Text>
        )}
        <Text muted size="xs">{t('auth.capability.explains')}</Text>
      </Card>

      <Card>
        <Text weight="medium">The assessment form arrives in the next step.</Text>
        <Text muted size="sm">
          {counts.pending + counts.blocked} changes are waiting on this device and will sync
          on their own.
        </Text>
      </Card>

      <Button label={t('sync.detail.title')} variant="secondary" onPress={() => router.push('/sync')} />
      <Button
        label="Citizen app"
        variant="secondary"
        onPress={() => {
          setSurface('citizen');
          router.replace('/(citizen)');
        }}
      />
    </Screen>
  );
}
