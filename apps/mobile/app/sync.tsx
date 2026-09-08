/**
 * Sync detail: what the strip says, expanded.
 *
 * The strip answers "is my work safe" in one line. This screen answers the follow-up
 * questions - what exactly is waiting, what needs me, and what happens next - and it is
 * where the two states that need a person are resolved.
 *
 * It never offers a "clear the queue" button. Every route off this screen either moves
 * work to the server or writes it to a file that can be handed to the district office.
 */

import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { Button, Card, Heading, Screen, Text } from '../src/components/primitives.js';
import { describeAge } from '../src/offline/status/model.js';
import { exportQueue } from '../src/offline/export.js';
import { writeQueueExport } from '../src/offline/export-file.js';
import { useLocale, useOffline } from '../src/providers/index.js';
import { SPACE } from '../src/theme/index.js';

export default function SyncScreen() {
  const { t } = useLocale();
  const { counts, mediaCounts, strip, engine, log, deviceId, syncNow, refresh } = useOffline();
  const [exported, setExported] = useState<string | null>(null);
  const [missingSeq, setMissingSeq] = useState<number | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);

  useEffect(() => {
    if (!log) return;
    void log.device().then((device) => {
      setMissingSeq(device.blocked_on_seq);
      setLastSyncedAt(device.last_synced_at ? Date.parse(device.last_synced_at) : null);
    });
  }, [log, counts]);

  const queued = counts.pending + counts.syncing + counts.blocked;
  const attention = counts.conflict + counts.failed + mediaCounts.failed;
  const age = lastSyncedAt === null ? null : describeAge(Date.now() - lastSyncedAt);

  return (
    <Screen>
      <Heading>{t('sync.detail.title')}</Heading>

      <Card>
        <Text weight="medium">{t(strip.messageKey, strip.values)}</Text>
        <Text muted size="sm">
          {t('sync.detail.queued', { count: queued + mediaCounts.pending + mediaCounts.deferred })}
        </Text>
        {attention > 0 ? (
          <Text size="sm">{t('sync.detail.attention', { count: attention })}</Text>
        ) : null}
        <Text muted size="xs">
          {age === null
            ? t('sync.detail.never')
            : t('sync.detail.lastSynced', {
                age: t(`sync.status.offline.${age.key}`, { count: queued, age: age.value }),
              })}
        </Text>
        <Text muted size="xs">
          {t('sync.detail.device', { id: deviceId ?? '-' })}
        </Text>
      </Card>

      {missingSeq !== null ? (
        <Card>
          <Text weight="semibold">{t('sync.gap.title')}</Text>
          {/* Names the sequence number. A support call that starts with a number is a
              much shorter call than one that starts with "it stopped working". */}
          <Text size="sm">{t('sync.gap.body', { seq: missingSeq })}</Text>
        </Card>
      ) : null}

      {counts.conflict > 0 ? (
        <Card>
          <Text weight="semibold">{t('sync.conflict.title')}</Text>
          <Text size="sm">{t('sync.conflict.body')}</Text>
        </Card>
      ) : null}

      <View style={{ gap: SPACE[2] }}>
        <Button
          label={t('action.syncNow')}
          onPress={() => {
            void syncNow();
          }}
          disabled={engine === null}
        />
        <Button
          label={t('action.exportQueue')}
          variant="secondary"
          onPress={() => {
            void (async () => {
              if (!log) return;
              const payload = await exportQueue(log);
              setExported(await writeQueueExport(payload));
              refresh();
            })();
          }}
        />
      </View>

      {exported !== null ? (
        <Text muted size="xs">
          {exported}
        </Text>
      ) : null}
    </Screen>
  );
}
