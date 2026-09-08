/**
 * The language picker.
 *
 * Reachable at any time, and shown before login on a first launch where the device
 * locale is not one SARANA speaks. Each language is written in its own script and never
 * translated - "Sinhala" in English is no use to someone who cannot read English, which
 * is the entire population this screen exists for.
 */

import { useRouter } from 'expo-router';

import { Button, Heading, Screen, Text } from '../src/components/primitives.js';
import { useLocale } from '../src/providers/index.js';
import { LOCALES, LOCALE_NAMES } from '../src/i18n/index.js';

export default function LanguageScreen() {
  const { locale, setLocale, t, dismissPrompt } = useLocale();
  const router = useRouter();

  return (
    <Screen>
      <Heading>{t('language.choose')}</Heading>
      {LOCALES.map((candidate) => (
        <Button
          key={candidate}
          // The name of the language, in that language. Never translated.
          label={LOCALE_NAMES[candidate]}
          variant={candidate === locale ? 'primary' : 'secondary'}
          onPress={() => setLocale(candidate)}
        />
      ))}
      <Button
        label={t('language.confirm')}
        onPress={() => {
          dismissPrompt();
          router.replace('/');
        }}
      />
      <Text muted size="xs">
        {t('app.simulated')}
      </Text>
    </Screen>
  );
}
