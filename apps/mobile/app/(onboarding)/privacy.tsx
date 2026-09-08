/**
 * The privacy screen, shown once at onboarding.
 *
 * Before anything personal is collected, not after. The same four sections as
 * `/(citizen)/privacy`, imported from there rather than restated - one copy, so the
 * version a person reads on day one is the version they can go back to in March.
 */

import { useRouter } from 'expo-router';

import { Button, Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { PRIVACY_SECTIONS } from '../(citizen)/privacy.js';
import { useLocale } from '../../src/providers/index.js';

export default function OnboardingPrivacy() {
  const { t } = useLocale();
  const router = useRouter();

  return (
    <Screen>
      <Heading>{t('onboarding.privacyTitle')}</Heading>

      {PRIVACY_SECTIONS.map(([title, bodyKey]) => (
        <Card key={title}>
          <Text weight="semibold">{t(title)}</Text>
          <Text size="sm">{t(bodyKey)}</Text>
        </Card>
      ))}

      <Text size="xs" muted>
        {t('privacy.note')}
      </Text>
      <Button
        label={t('action.understood')}
        onPress={() => router.replace('/(onboarding)/household')}
      />
    </Screen>
  );
}
