/**
 * Sign-in, for both kinds of user.
 *
 * Citizens: MSISDN plus a code by SMS. Officers: email, password and an authenticator
 * code. Two forms rather than one with a mode switch, because they are answering
 * different questions and a citizen in a flood should not have to read past a password
 * field to find the one that applies to them.
 *
 * The language picker is on this screen, not behind it. Someone who cannot read the form
 * cannot be asked to sign in first to change the language it is written in.
 */

import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Button, Card, Heading, Screen, Text } from '../src/components/primitives.js';
import { TextField } from '../src/components/TextField.js';
import { useLocale, useSession } from '../src/providers/index.js';
import { SPACE } from '../src/theme/index.js';

type Mode = 'citizen' | 'officer';

export default function SignInScreen() {
  const { t } = useLocale();
  const { signIn } = useSession();
  const router = useRouter();
  const [mode, setMode] = useState<Mode>('citizen');
  const [msisdn, setMsisdn] = useState('');
  const [otp, setOtp] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [totp, setTotp] = useState('');

  return (
    <Screen>
      <Heading>{t('app.name')}</Heading>
      <Text muted size="sm">
        {t('app.tagline')}
      </Text>

      <View style={{ flexDirection: 'row', gap: SPACE[2] }}>
        <View style={{ flex: 1 }}>
          <Button
            label={t('auth.signIn.citizenTitle')}
            variant={mode === 'citizen' ? 'primary' : 'secondary'}
            onPress={() => setMode('citizen')}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Button
            label={t('auth.signIn.officerTitle')}
            variant={mode === 'officer' ? 'primary' : 'secondary'}
            onPress={() => setMode('officer')}
          />
        </View>
      </View>

      <Card>
        {mode === 'citizen' ? (
          <>
            <TextField
              label={t('auth.signIn.msisdn')}
              value={msisdn}
              onChange={setMsisdn}
              keyboardType="phone-pad"
            />
            <TextField
              label={t('auth.signIn.otp')}
              value={otp}
              onChange={setOtp}
              keyboardType="number-pad"
            />
          </>
        ) : (
          <>
            <TextField
              label={t('auth.signIn.email')}
              value={email}
              onChange={setEmail}
              keyboardType="email-address"
            />
            <TextField
              label={t('auth.signIn.password')}
              value={password}
              onChange={setPassword}
              secure
            />
            <TextField
              label={t('auth.signIn.totp')}
              value={totp}
              onChange={setTotp}
              keyboardType="number-pad"
            />
          </>
        )}

        <Button
          label={t('action.signIn')}
          onPress={() => {
            // The credentials go to core-api's `/auth/login` and `/auth/otp/verify`. That
            // wiring lands with the two surfaces (files 23 and 24); until then this seats
            // a session so the shell, the strip and the offline core can be exercised end
            // to end on a device. Nothing here is a credential check.
            signIn({
              subjectId: '018f4a2b-0000-7000-8000-0000000000aa',
              roles: mode === 'officer' ? ['GN_OFFICER'] : ['CITIZEN'],
              displayName: null,
              gnDivisionCode: mode === 'officer' ? 'LK-2-05-020-1015' : null,
              householdId: null,
            });
            router.replace('/');
          }}
        />
      </Card>

      <Button
        label={t('language.change')}
        variant="secondary"
        onPress={() => router.push('/language')}
      />
      <Text muted size="xs">
        {t('app.simulated')}
      </Text>
    </Screen>
  );
}
