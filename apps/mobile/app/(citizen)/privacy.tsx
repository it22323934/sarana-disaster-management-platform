/**
 * What we collect, and who sees it.
 *
 * Shown at onboarding and reachable from settings at any time. Sri Lanka's PDPA
 * substantive provisions are not yet commenced (ADR-011), so none of this is currently a
 * legal obligation - which is exactly why it is here. The platform is asking frightened
 * people for their location, and earning that has to be more than a checkbox.
 *
 * Four questions, in the order a person actually asks them, written at a level someone
 * with no technical background can read, in all three languages. No defined terms, no
 * "processing", no "data controller".
 */

import { useRouter } from 'expo-router';

import { Button, Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { useLocale } from '../../src/providers/index.js';

/** The four sections, in the order a person asks them. Shared with the onboarding copy. */
export const PRIVACY_SECTIONS = [
  ['privacy.collectTitle', 'privacy.collect'],
  ['privacy.shareTitle', 'privacy.share'],
  ['privacy.keepTitle', 'privacy.keep'],
  ['privacy.deleteTitle', 'privacy.delete'],
] as const;

export default function PrivacyScreen() {
  const { t } = useLocale();
  const router = useRouter();

  return (
    <Screen>
      <Heading>{t('privacy.title')}</Heading>

      {PRIVACY_SECTIONS.map(([title, bodyKey]) => (
        <Card key={title}>
          <Text weight="semibold">{t(title)}</Text>
          <Text size="sm">{t(bodyKey)}</Text>
        </Card>
      ))}

      <Text size="xs" muted>
        {t('privacy.note')}
      </Text>

      <Button label={t('action.understood')} onPress={() => router.back()} />
    </Screen>
  );
}
