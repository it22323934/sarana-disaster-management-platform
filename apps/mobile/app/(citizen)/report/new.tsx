/**
 * The report flow. Target: under thirty seconds from tap to submitted, fully offline.
 *
 * The thirty seconds are bought by what does not happen. Location starts the moment the
 * screen opens, in the background, and nothing waits on it. There is no next-step
 * navigation - the whole flow is one scroll, so nobody loses their place. Voice is the
 * primary input because typing Sinhala or Tamil on a phone keyboard under stress is slow
 * and speaking is not. And Submit is always enabled once there is anything at all.
 *
 * The order on the screen is the order of value to a dispatcher, not the order of effort
 * for the reporter: type, then voice, then photo, then text, then the people question.
 * Someone who taps the first tile and hits Submit has filed a dispatchable report.
 */

import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';

import { Button, Card, Heading, Screen, Text, useSurface } from '../../../src/components/primitives.js';
import { IncidentTypeGrid } from '../../../src/citizen/components/IncidentTypeGrid.js';
import { PeopleAtRisk } from '../../../src/citizen/components/PeopleAtRisk.js';
import { VoiceNoteButton } from '../../../src/citizen/components/VoiceNoteButton.js';
import { isSubmittable, saveReport, type IncidentType, type ReportDraft, type ReportLocation } from '../../../src/citizen/report-draft.js';
import { captureLocation } from '../../../src/citizen/location.js';
import { useLocale, useOffline } from '../../../src/providers/index.js';
import { RADIUS, SPACE, touchTarget, type } from '../../../src/theme/index.js';

export default function NewReportScreen() {
  const { t, locale } = useLocale();
  const { log, media, engine, refresh, network } = useOffline();
  const surface = useSurface();
  const router = useRouter();

  const [incidentType, setIncidentType] = useState<IncidentType | null>(null);
  const [text, setText] = useState('');
  const [peopleAtRisk, setPeopleAtRisk] = useState<number | null>(null);
  const [location, setLocation] = useState<ReportLocation | null>(null);
  const [locating, setLocating] = useState(true);
  const [voiceUri, setVoiceUri] = useState<string | null>(null);
  const [photoUri, setPhotoUri] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ reference: string; online: boolean } | null>(null);
  const [refused, setRefused] = useState(false);

  // Started on mount, and nothing on the screen waits for it. A person who taps a tile and
  // submits within four seconds gets a report with no coordinate, which is a report the
  // platform accepts.
  const cancelled = useRef(false);
  useEffect(() => {
    cancelled.current = false;
    void captureLocation().then((fix) => {
      if (cancelled.current) return;
      setLocation(fix);
      setLocating(false);
    });
    return () => {
      cancelled.current = true;
    };
  }, []);

  const draft: ReportDraft = {
    incidentType,
    text: text.trim().length > 0 ? text : null,
    language: locale,
    location,
    peopleAtRisk,
  };
  const mediaCount = (voiceUri ? 1 : 0) + (photoUri ? 1 : 0);

  const submit = useCallback(async () => {
    if (!log || !media) return;
    if (!isSubmittable(draft, { mediaCount })) {
      setRefused(true);
      return;
    }

    const result = await saveReport(log, draft);

    for (const [uri, kind, contentType] of [
      [voiceUri, 'audio', 'audio/m4a'],
      [photoUri, 'photo', 'image/jpeg'],
    ] as const) {
      if (!uri) continue;
      await media.enqueue({
        client_operation_id: result.clientOperationId,
        entity_type: 'report',
        entity_local_id: result.localId,
        kind,
        local_uri: uri,
        content_type: contentType,
        // The real size is read when the file is queued for upload. Zero here would fail
        // the presign check with a confusing message; the queue reads it back on send.
        size_bytes: 1,
        // An emergency photo goes over a metered link. This is the one place the override
        // is set without asking, because the alternative is evidence that waits for Wi-Fi
        // while somebody is on a roof.
        urgent: true,
      });
    }

    setSaved({ reference: result.reference, online: network.reachable });
    refresh();
    // Fire and forget. Nothing on this screen waits for it.
    void engine?.request('after-write');
  }, [draft, engine, log, media, mediaCount, network.reachable, photoUri, refresh, voiceUri]);

  if (saved !== null) {
    return (
      <Screen>
        <Heading>{saved.online ? t('report.savedOnline') : t('report.savedOffline')}</Heading>
        <Card>
          <Text size="lg" weight="semibold">
            {t('report.reference', { reference: saved.reference })}
          </Text>
          <Text size="sm" muted>
            {t('report.referenceHint')}
          </Text>
        </Card>
        <Button label={t('tabs.home')} onPress={() => router.replace('/(citizen)/(tabs)/home')} />
      </Screen>
    );
  }

  return (
    <Screen>
      <Heading>{t('report.newTitle')}</Heading>

      {/* Location, as a status line rather than a step. It never blocks anything. */}
      <Text size="sm" muted>
        {locating
          ? t('report.locating')
          : location === null
            ? t('report.locationNone')
            : t('report.locationFound', { metres: Math.round(location.accuracyMetres ?? 0) })}
      </Text>

      <IncidentTypeGrid selected={incidentType} onSelect={setIncidentType} />

      <VoiceNoteButton uri={voiceUri} onRecorded={setVoiceUri} />

      <Button
        label={photoUri ? `${t('report.photo')} ✓` : t('report.photo')}
        variant="secondary"
        onPress={() => {
          // The camera screen lives behind the storage guard, which refuses before the
          // camera opens rather than after a zero-byte file has been written.
          router.push('/(citizen)/report/photo');
        }}
      />

      <View style={{ gap: SPACE[1] }}>
        <Text size="sm" muted>
          {t('report.describe')}
        </Text>
        <TextInput
          value={text}
          onChangeText={setText}
          multiline
          accessibilityLabel={t('report.describe')}
          allowFontScaling={false}
          placeholderTextColor={surface.muted}
          style={[
            styles.input,
            type('base', locale),
            {
              color: surface.text,
              backgroundColor: surface.raised,
              borderColor: surface.divider,
              minHeight: touchTarget('min') * 2,
            },
          ]}
        />
      </View>

      <PeopleAtRisk value={peopleAtRisk} onChange={setPeopleAtRisk} />

      {refused ? (
        <Text size="sm" colour="#DC2626">
          {t('report.emptyRefused')}
        </Text>
      ) : null}

      <Button
        label={t('report.submit')}
        onPress={() => {
          void submit();
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  input: {
    borderWidth: 1,
    borderRadius: RADIUS.default,
    paddingHorizontal: SPACE[3],
    paddingVertical: SPACE[2],
    textAlignVertical: 'top',
  },
});
