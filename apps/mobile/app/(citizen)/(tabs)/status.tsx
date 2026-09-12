/**
 * My reports, and where each one has got to.
 *
 * Every line on this screen is a sentence, never a status code. `reportProgress` in
 * `citizen/status-language.ts` decides which sentence, and it is tested twelve ways -
 * because the wrong sentence here is either a person waiting for help that was never
 * dispatched, or a person who stops waiting when it is on the way.
 *
 * A queued report shows its queue position and when the device last tried. That is the
 * offline promise being kept in the one place it is checkable.
 */

import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';

import { Card, Heading, Screen, Text } from '../../../src/components/primitives.js';
import { useLocalReports } from '../../../src/citizen/cache.js';
import { reportProgress } from '../../../src/citizen/status-language.js';
import { describeAge } from '../../../src/offline/status/model.js';
import type { OperationRecord } from '../../../src/offline/log/types.js';
import { useLocale, useOffline } from '../../../src/providers/index.js';
import { SPACE, touchTarget } from '../../../src/theme/index.js';

export default function StatusTab() {
  const { t } = useLocale();
  const { db, log, counts } = useOffline();
  const router = useRouter();
  // `counts` changes on every sync, which is exactly when a report's status can change.
  const reports = useLocalReports(db, counts.synced + counts.pending);
  const [operations, setOperations] = useState<Record<string, OperationRecord>>({});

  useEffect(() => {
    if (!log) return;
    void log.all().then((all) => {
      const byEntity: Record<string, OperationRecord> = {};
      for (const record of all) {
        if (record.entity_type === 'report') byEntity[record.entity_local_id] = record;
      }
      setOperations(byEntity);
    });
  }, [log, counts]);

  if (reports.length === 0) {
    return (
      <Screen>
        <Heading>{t('tabs.status')}</Heading>
        <Text muted>{t('status.none')}</Text>
      </Screen>
    );
  }

  return (
    <Screen>
      <Heading>{t('tabs.status')}</Heading>
      {reports.map((report) => {
        const operation = operations[report.local_id];
        const progress = reportProgress({
          // Until a read-back from incident-svc exists, the device knows only whether the
          // report arrived. Saying "received" for a synced report is true and is where the
          // honest floor is; the richer states arrive with the status poll.
          incidentStatus: report.server_id ? 'REPORTED' : null,
          processingStatus: null,
          dispatchStatus: null,
          localStatus: operation?.status ?? 'pending',
        });
        const age = describeAge(Date.now() - Date.parse(report.created_at));

        return (
          <Pressable
            key={report.local_id}
            onPress={() => router.push(`/(citizen)/report/${report.local_id}`)}
            accessibilityRole="button"
            style={{ minHeight: touchTarget('min') }}
          >
            <Card>
              <View style={{ gap: SPACE[1] }}>
                <Text weight="medium">
                  {t('report.reference', { reference: report.public_ref ?? report.local_id })}
                </Text>
                <Text size="sm">{t(progress.messageKey)}</Text>
                <Text size="xs" muted>
                  {report.server_id
                    ? t('status.submittedAt', {
                        when: t(`time.age.${age.key}`, { age: age.value }),
                      })
                    : t('status.queuedSince', {
                        when: t(`time.age.${age.key}`, { age: age.value }),
                      })}
                </Text>
              </View>
            </Card>
          </Pressable>
        );
      })}
    </Screen>
  );
}
