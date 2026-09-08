/**
 * Settings.
 *
 * Three things, and one of them is a control that visibly stops short of what a user
 * might expect. The alert threshold ends at level 2, with a sentence saying why: **an
 * evacuation order is not a notification preference.** The alternative - a slider that
 * goes to 4 and is then ignored by `decideNotification` - would be a setting that lies.
 */

import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Switch, View } from 'react-native';

import { Button, Card, Heading, Screen, Text, useSurface } from '../../src/components/primitives.js';
import {
  DEFAULT_PREFERENCES,
  HIGHEST_MUTABLE_CLASS,
  type NotificationPreferences,
} from '../../src/citizen/notification-policy.js';

/**
 * The levels the control offers.
 *
 * Derived from the policy rather than typed out, so the control cannot drift above what
 * `decideNotification` will honour. A slider that went to 4 and was then ignored would be
 * a setting that lies.
 */
const MUTABLE_LEVELS = Array.from({ length: HIGHEST_MUTABLE_CLASS + 1 }, (_, level) => level);
import { LOCALE_NAMES, LOCALES } from '../../src/i18n/index.js';
import { useLocale, useOffline, useSession } from '../../src/providers/index.js';
import { RADIUS, SPACE, touchTarget } from '../../src/theme/index.js';

export default function SettingsScreen() {
  const { t, locale, setLocale } = useLocale();
  const { counts } = useOffline();
  const { attemptSignOut } = useSession();
  const surface = useSurface();
  const router = useRouter();
  const [preferences, setPreferences] = useState<NotificationPreferences>(DEFAULT_PREFERENCES);
  const [refusal, setRefusal] = useState<string | null>(null);

  const unsynced = counts.pending + counts.syncing + counts.blocked + counts.failed;
  const attention = counts.conflict + counts.failed;

  return (
    <Screen>
      <Heading>{t('settings.title')}</Heading>

      <Card>
        <Text weight="medium">{t('language.change')}</Text>
        <View style={{ gap: SPACE[2] }}>
          {LOCALES.map((candidate) => (
            <Pressable
              key={candidate}
              onPress={() => setLocale(candidate)}
              accessibilityRole="radio"
              accessibilityState={{ selected: candidate === locale }}
              style={[
                styles.option,
                {
                  minHeight: touchTarget('min'),
                  backgroundColor: candidate === locale ? '#0E7C86' : surface.card,
                  borderColor: candidate === locale ? '#0E7C86' : surface.divider,
                },
              ]}
            >
              <Text colour={candidate === locale ? '#FFFFFF' : surface.text}>
                {LOCALE_NAMES[candidate]}
              </Text>
            </Pressable>
          ))}
        </View>
      </Card>

      <Card>
        <Text weight="medium">{t('settings.notifications')}</Text>
        <Text size="sm" muted>
          {t('settings.minimumClass')}
        </Text>
        <View style={{ gap: SPACE[2] }}>
          {MUTABLE_LEVELS.map((level) => (
            <Pressable
              key={level}
              onPress={() => setPreferences((current) => ({ ...current, minimumAlertClass: level }))}
              accessibilityRole="radio"
              accessibilityState={{ selected: preferences.minimumAlertClass === level }}
              style={[
                styles.option,
                {
                  minHeight: touchTarget('min'),
                  backgroundColor:
                    preferences.minimumAlertClass === level ? '#0E7C86' : surface.card,
                  borderColor: preferences.minimumAlertClass === level ? '#0E7C86' : surface.divider,
                },
              ]}
            >
              <Text colour={preferences.minimumAlertClass === level ? '#FFFFFF' : surface.text}>
                {t(`settings.class.${level}`)}
              </Text>
            </Pressable>
          ))}
        </View>
        {/* The control stops at HIGHEST_MUTABLE_CLASS and the sentence says why, rather
            than offering a level the policy would then ignore. */}
        <Text size="sm">{t('settings.cannotMute')}</Text>

        <View style={styles.row}>
          <Text size="sm">{t('settings.aidUpdates')}</Text>
          <Switch
            value={preferences.aidUpdates}
            onValueChange={(value) =>
              setPreferences((current) => ({ ...current, aidUpdates: value }))
            }
            accessibilityLabel={t('settings.aidUpdates')}
          />
        </View>
        <View style={styles.row}>
          <Text size="sm">{t('settings.reportUpdates')}</Text>
          <Switch
            value={preferences.reportUpdates}
            onValueChange={(value) =>
              setPreferences((current) => ({ ...current, reportUpdates: value }))
            }
            accessibilityLabel={t('settings.reportUpdates')}
          />
        </View>
      </Card>

      <Button
        label={t('settings.privacy')}
        variant="secondary"
        onPress={() => router.push('/(citizen)/privacy')}
      />

      {refusal ? (
        <Card>
          <Text>{refusal}</Text>
          <Button label={t('action.syncNow')} onPress={() => router.push('/sync')} />
        </Card>
      ) : null}

      <Button
        label={t('settings.signOut')}
        variant="danger"
        onPress={() => {
          void (async () => {
            const verdict = await attemptSignOut({
              unsyncedCount: unsynced,
              attentionCount: attention,
            });
            if (verdict.allowed) {
              router.replace('/sign-in');
            } else {
              // Names the number. "You have unsaved changes" is the message that gets
              // dismissed; "4 changes have not reached the server" is the one that does not.
              setRefusal(t(verdict.messageKey, verdict.values));
            }
          })();
        }}
      />
      <Text size="xs" muted>
        {t('app.simulated')}
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  option: {
    justifyContent: 'center',
    padding: SPACE[3],
    borderRadius: RADIUS.default,
    borderWidth: 1,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: touchTarget('min'),
    gap: SPACE[3],
  },
});
