/**
 * Linking a household. Optional, and it says so first.
 *
 * Skipping is a real choice with a real button, not a small link. A citizen who never
 * links still gets warnings and can still report - the only thing they lose is the Aid
 * tab, and that tab says what to do about it rather than rendering an empty screen.
 */

import { useRouter } from 'expo-router';
import { useState } from 'react';

import { Button, Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { TextField } from '../../src/components/TextField.js';
import { useLocale } from '../../src/providers/index.js';

export default function HouseholdScreen() {
  const { t } = useLocale();
  const router = useRouter();
  const [reference, setReference] = useState('');

  return (
    <Screen>
      <Heading>{t('onboarding.householdTitle')}</Heading>
      <Text size="sm">{t('onboarding.householdWhy')}</Text>

      <Card>
        <TextField
          label={t('onboarding.householdTitle')}
          value={reference}
          onChange={setReference}
          autoCapitalize="characters"
        />
        <Button
          label={t('action.save')}
          onPress={() => router.replace('/(citizen)/(tabs)/home')}
        />
      </Card>

      <Button
        label={t('onboarding.householdSkip')}
        variant="secondary"
        onPress={() => router.replace('/(citizen)/(tabs)/home')}
      />
    </Screen>
  );
}
