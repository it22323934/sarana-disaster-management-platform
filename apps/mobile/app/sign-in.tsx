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
import { TextInput, View } from 'react-native';

import { Button, Card, Heading, Screen, Text, useSurface } from '../src/components/primitives.js';
import { useLocale, useSession } from '../src/providers/index.js';
import { RADIUS, SPACE, touchTarget, type } from '../src/theme/index.js';

type Mode = 'citizen' | 'officer';

function Field({
  label,
  value,
  onChange,
  keyboardType,
  secure,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  keyboardType?: 'phone-pad' | 'number-pad' | 'email-address';
  secure?: boolean;
}) {
  const { locale } = useLocale();
  const surface = useSurface();
  const metrics = type('base', locale);

  return (
    <View style={{ gap: SPACE[1] }}>
      <Text size="sm" muted>
        {label}
      </Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        keyboardType={keyboardType}
        secureTextEntry={secure}
        autoCapitalize="none"
        accessibilityLabel={label}
        allowFontScaling={false}
        placeholderTextColor={surface.muted}
        style={{
          ...metrics,
          color: surface.text,
          backgroundColor: surface.raised,
          borderColor: surface.divider,
          borderWidth: 1,
          borderRadius: RADIUS.default,
          paddingHorizontal: SPACE[3],
          minHeight: touchTarget('min'),
        }}
      />
    </View>
  );
}

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
            <Field
              label={t('auth.signIn.msisdn')}
              value={msisdn}
              onChange={setMsisdn}
              keyboardType="phone-pad"
            />
            <Field
              label={t('auth.signIn.otp')}
              value={otp}
              onChange={setOtp}
              keyboardType="number-pad"
            />
          </>
        ) : (
          <>
            <Field
              label={t('auth.signIn.email')}
              value={email}
              onChange={setEmail}
              keyboardType="email-address"
            />
            <Field
              label={t('auth.signIn.password')}
              value={password}
              onChange={setPassword}
              secure
            />
            <Field
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
