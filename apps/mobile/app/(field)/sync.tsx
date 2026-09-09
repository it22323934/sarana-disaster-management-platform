/**
 * `/(field)/sync` — the queue, made legible, plus the two recovery doors.
 *
 * The brief asks for every pending operation with what it is, when it was created, how
 * many attempts, and the last error in plain language; conflicts side by side with an
 * explicit choice; manual retry; and an export.
 *
 * **Nothing on this screen resolves a conflict on the officer's behalf.** A conflict means
 * the server refused something the officer believes they did, in a division only they were
 * standing in. Auto-merging would settle that in favour of whoever wrote the merge rule,
 * silently, in a record that later becomes money. The buttons are the choice; there is no
 * default and no "resolve all".
 *
 * The import door is beside the export one because they are the same story from two ends: a
 * failing handset writes the file, a replacement reads it. Separating them across two
 * screens would leave an officer holding a file and no obvious way to use it.
 */

import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { Button, Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { useLocale, useOffline } from '../../src/providers/index.js';
import { SPACE } from '../../src/theme/index.js';
import { describeConflict, type ConflictSummary } from '../../src/field/conflicts.js';
import type { OperationRecord } from '../../src/offline/log/types.js';

export default function FieldSync() {
  const { t } = useLocale();
  const { log, counts, strip, syncNow, refresh } = useOffline();
  const router = useRouter();

  const [pending, setPending] = useState<OperationRecord[]>([]);
  const [conflicts, setConflicts] = useState<ConflictSummary[]>([]);

  useEffect(() => {
    if (!log) return;
    let cancelled = false;

    void (async () => {
      const all = await log.all();
      if (cancelled) return;

      const unsynced = all.filter((record) => record.status !== 'synced');
      setPending(unsynced);

      // How many operations sit behind each conflict, so the screen can say what resolving
      // it would release. Sequence ordering means everything after a refusal waits.
      setConflicts(
        unsynced
          .filter((record) => record.status === 'conflict')
          .map((record) =>
            describeConflict(record, {
              blocking: unsynced.filter((other) => other.seq > record.seq).length,
            }),
          ),
      );
    })();

    return () => {
      cancelled = true;
    };
  }, [log, counts]);

  return (
    <Screen>
      <Heading>{t('field.sync.title')}</Heading>
      {/* The strip never carries an English literal: it is the one component on every
          screen, and it renders in whichever of three languages the officer chose. */}
      <Text size="sm">{t(strip.messageKey, strip.values)}</Text>

      {conflicts.map((conflict) => (
        <Card key={conflict.clientOperationId}>
          <Text weight="semibold">{t('field.sync.conflictTitle')}</Text>
          <Text size="sm">{conflict.explanation}</Text>
          {conflict.blocking > 0 ? (
            <Text size="sm">
              {t('field.sync.conflictBlocking', { count: conflict.blocking })}
            </Text>
          ) : null}

          {/* Side by side, every field, including the ones that agree. An officer deciding
              whether to keep their version needs the whole record, not a diff of the parts
              a rule thought were interesting. */}
          {conflict.fields.map((field) => (
            <View key={field.field} style={{ gap: SPACE[1] }}>
              <Text weight="medium" size="sm">{field.field}</Text>
              <Text size="xs">
                {t('field.sync.conflictLocal')}: {field.local}
              </Text>
              <Text size="xs">
                {t('field.sync.conflictServer')}: {field.server ?? '—'}
              </Text>
            </View>
          ))}

          {/* The choices this conflict actually offers. `accept-server` is absent where the
              server holds no competing record, because "accept nothing" is `discard` under
              a misleading label. */}
          {conflict.choices.includes('keep-local') ? (
            <Button label={t('field.sync.keepLocal')} variant="secondary" onPress={refresh} />
          ) : null}
          {conflict.choices.includes('accept-server') ? (
            <Button label={t('field.sync.acceptServer')} variant="secondary" onPress={refresh} />
          ) : null}
          {conflict.choices.includes('discard') ? (
            <Button label={t('field.sync.discard')} variant="danger" onPress={refresh} />
          ) : null}
          <Text muted size="xs">{t('field.sync.chooseFirst')}</Text>
        </Card>
      ))}

      {pending
        .filter((record) => record.status !== 'conflict')
        .map((record) => (
          <Card key={record.client_operation_id}>
            <Text weight="medium" size="sm">
              {record.entity_type} · {record.op}
            </Text>
            <Text muted size="xs">{new Date(record.created_at).toLocaleString()}</Text>
            <Text muted size="xs">
              {t('sync.detail.attention', { count: record.attempt_count })}
            </Text>
            {/* The server's own sentence, not a status code. */}
            {record.last_error ? <Text size="xs">{record.last_error}</Text> : null}
          </Card>
        ))}

      <Button label={t('field.sync.retry')} onPress={() => void syncNow()} />

      <Card>
        <Text weight="semibold">{t('field.sync.exportTitle')}</Text>
        <Text muted size="sm">{t('field.sync.exportBody')}</Text>
        <Button
          label={t('field.sync.export')}
          variant="secondary"
          onPress={() => router.push('/sync')}
        />
      </Card>

      <Card>
        <Text weight="semibold">{t('field.sync.importTitle')}</Text>
        <Text muted size="sm">{t('field.sync.importBody')}</Text>
        <Button
          label={t('field.sync.import')}
          variant="secondary"
          onPress={() => router.push('/sync')}
        />
      </Card>
    </Screen>
  );
}
