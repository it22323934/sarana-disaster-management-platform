/**
 * The phone number, and why we want it.
 *
 * The reason is on the screen above the field, not behind a link. Someone being asked for
 * their number by a government app during a disaster is owed the sentence explaining what
 * it is for, before they type it.
 */

import { useRouter } from 'expo-router';
import { useState } from 'react';

import { Button, Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { TextField } from '../../src/components/TextField.js';
import { useLocale } from '../../src/providers/index.js';

export default function PhoneScreen() {
  const { t } = useLocale();
  const router = useRouter();
  const [msisdn, setMsisdn] = useState('');
  const [otp, setOtp] = useState('');
  const [sent, setSent] = useState(false);

  return (
    <Screen>
      <Heading>{t('onboarding.phoneTitle')}</Heading>
      <Text size="sm">{t('onboarding.phoneWhy')}</Text>

      <Card>
        <TextField
          label={t('auth.signIn.msisdn')}
          value={msisdn}
          onChange={setMsisdn}
          keyboardType="phone-pad"
        />
        {sent ? (
          <TextField
            label={t('auth.signIn.otp')}
            value={otp}
            onChange={setOtp}
            keyboardType="number-pad"
          />
        ) : null}
        <Button
          label={sent ? t('action.signIn') : t('auth.signIn.requestOtp')}
          onPress={() => {
            // `/auth/otp/request` and `/auth/otp/verify` exist on core-api and the client
            // is wired. Calling them is the last step of this surface and is not done yet;
            // saying so in a comment beats a screen that pretends to have sent an SMS.
            if (!sent) setSent(true);
            else router.replace('/(onboarding)/privacy');
          }}
        />
      </Card>
    </Screen>
  );
}
