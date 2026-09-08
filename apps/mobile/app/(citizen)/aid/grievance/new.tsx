/**
 * Raising a grievance.
 *
 * **This is a right, not a support ticket.** The screen says so at the top, it never asks
 * the household to justify using it, and the SLA date is shown before they submit rather
 * than after - so what the platform owes them is a commitment made in advance, not a
 * number produced once they have already complained.
 *
 * It works offline like everything else, which is what makes the promise real: a household
 * in a cut-off division has the same right as one in Colombo.
 */

import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Button, Card, Heading, Screen, Text, useSurface } from '../../../../src/components/primitives.js';
import {
  REASON_KEYS,
  SLA_DAYS,
  saveGrievance,
  slaDueAt,
  type GrievanceSubject,
} from '../../../../src/citizen/grievance-draft.js';
import { translator, LOCALES } from '../../../../src/i18n/index.js';
import { useLocale, useOffline, useSession } from '../../../../src/providers/index.js';
import { TextField } from '../../../../src/components/TextField.js';
import { RADIUS, SPACE, touchTarget } from '../../../../src/theme/index.js';

export default function NewGrievanceScreen() {
  const params = useLocalSearchParams<{ subject?: string; id?: string; reason?: string }>();
  const { t, locale } = useLocale();
  const { log, engine, refresh, network } = useOffline();
  const { session } = useSession();
  const surface = useSurface();
  const router = useRouter();

  const subject = (params.subject ?? 'EXCLUSION') as GrievanceSubject;
  const [chosen, setChosen] = useState<string[]>(
    params.reason ? [`grievance.reason.${params.reason}`] : [],
  );
  const [freeText, setFreeText] = useState('');
  const [raised, setRaised] = useState<{ dueAt: number; queued: boolean } | null>(null);

  const submit = async () => {
    if (!log || !session) return;
    const result = await saveGrievance(log, {
      householdId: session.householdId ?? '',
      subjectType: subject,
      subjectId: params.id ?? null,
      // Resolved to all three languages here, from the catalogue. The household picks in
      // their own language and a DS officer reads it in theirs, without either of them
      // having to translate anything.
      reasons: chosen.map((key) => {
        const [si, ta, en] = LOCALES.map((candidate) => translator(candidate).t(key));
        return { si: si!, ta: ta!, en: en! };
      }),
      freeText,
      language: locale,
    });
    setRaised({ dueAt: result.slaDueAt, queued: !network.reachable });
    refresh();
    void engine?.request('after-write');
  };

  if (raised !== null) {
    return (
      <Screen>
        <Heading>{t('grievance.title')}</Heading>
        <Card>
          <Text>
            {raised.queued
              ? t('grievance.slaDueQueued', { days: SLA_DAYS[subject] })
              : t('grievance.slaDue', { date: new Date(raised.dueAt).toISOString().slice(0, 10) })}
          </Text>
          <Text size="sm" muted>
            {raised.queued ? t('report.savedOffline') : t('report.savedOnline')}
          </Text>
        </Card>
        <Button label={t('tabs.aid')} onPress={() => router.replace('/(citizen)/(tabs)/aid')} />
      </Screen>
    );
  }

  return (
    <Screen>
      <Heading>{t('grievance.title')}</Heading>
      <Text size="sm">{t('grievance.isARight')}</Text>

      {/* Before they submit, not after. What the platform owes is a commitment made in
          advance. */}
      <Text size="sm" muted>
        {t('grievance.slaDue', {
          date: new Date(slaDueAt(subject, Date.now())).toISOString().slice(0, 10),
        })}
      </Text>

      <Text weight="medium">{t('grievance.chooseReason')}</Text>
      <View style={{ gap: SPACE[2] }}>
        {REASON_KEYS[subject].map((key) => {
          const active = chosen.includes(key);
          return (
            <Pressable
              key={key}
              onPress={() =>
                setChosen((current) =>
                  active ? current.filter((entry) => entry !== key) : [...current, key],
                )
              }
              accessibilityRole="checkbox"
              accessibilityState={{ checked: active }}
              style={[
                styles.reason,
                {
                  minHeight: touchTarget('min'),
                  backgroundColor: active ? '#0E7C86' : surface.card,
                  borderColor: active ? '#0E7C86' : surface.divider,
                },
              ]}
            >
              <Text colour={active ? '#FFFFFF' : surface.text}>{t(key)}</Text>
            </Pressable>
          );
        })}
      </View>

      <TextField
        label={t('grievance.freeText')}
        value={freeText}
        onChange={setFreeText}
        multiline
      />

      <Button
        label={t('grievance.submit')}
        onPress={() => {
          void submit();
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  reason: {
    justifyContent: 'center',
    padding: SPACE[3],
    borderRadius: RADIUS.default,
    borderWidth: 1,
  },
});
