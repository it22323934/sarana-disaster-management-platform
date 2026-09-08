/**
 * One report, and what has happened to it.
 *
 * The ETA rule lives here in the form of a thing that is usually absent: `etaFor` returns
 * a range or nothing, and this screen renders exactly what it returns. **A missed ETA
 * during a disaster destroys trust in every subsequent message**, including the evacuation
 * order that comes next week - so a number that cannot be stood behind is not shown at
 * all, and the stage is shown instead.
 */

import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';

import { Button, Card, Heading, Screen, Text } from '../../../src/components/primitives.js';
import { etaFor, reportProgress } from '../../../src/citizen/status-language.js';
import type { LocalReport } from '../../../src/citizen/cache.js';
import type { OperationRecord } from '../../../src/offline/log/types.js';
import { describeAge } from '../../../src/offline/status/model.js';
import { useLocale, useOffline } from '../../../src/providers/index.js';

export default function ReportDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useLocale();
  const { db, log, counts, syncNow } = useOffline();
  const router = useRouter();
  const [report, setReport] = useState<LocalReport | null>(null);
  const [operation, setOperation] = useState<OperationRecord | null>(null);

  useEffect(() => {
    if (!db || !log || !id) return;
    void db
      .select<LocalReport>('SELECT * FROM report WHERE local_id = ?', [id])
      .then((rows) => setReport(rows[0] ?? null));
    void log.forEntity('report', id).then((records) => setOperation(records[0] ?? null));
  }, [db, id, log, counts]);

  if (!report) return <Screen />;

  const progress = reportProgress({
    incidentStatus: report.server_id ? 'REPORTED' : null,
    processingStatus: null,
    dispatchStatus: null,
    localStatus: operation?.status ?? 'pending',
  });

  // No plan is read back yet, so this is always the honest "not yet assigned". It is
  // rendered through `etaFor` rather than hard-coded so the day a plan does arrive, the
  // confidence floor is already being applied.
  const eta = etaFor({ estimatedMinutes: null, released: false, confidence: 0 });
  const age = describeAge(Date.now() - Date.parse(report.created_at));

  return (
    <Screen>
      <Heading>{t('report.reference', { reference: report.public_ref ?? report.local_id })}</Heading>

      <Card>
        <Text weight="medium">{t(progress.messageKey)}</Text>
        <Text size="sm" muted>
          {report.server_id
            ? t('status.submittedAt', { when: t(`time.age.${age.key}`, { age: age.value }) })
            : t('status.queuedSince', { when: t(`time.age.${age.key}`, { age: age.value }) })}
        </Text>
        {progress.responderMoving ? (
          <Text size="sm">
            {eta.kind === 'range'
              ? t('report.eta.range', { low: eta.lowMinutes, high: eta.highMinutes })
              : t(eta.reasonKey)}
          </Text>
        ) : null}
      </Card>

      {report.text ? (
        <Card>
          <Text size="sm" muted>
            {t('report.describe')}
          </Text>
          <Text>{report.text}</Text>
        </Card>
      ) : null}

      {report.incident_type ? (
        <Text size="sm" muted>
          {t(`report.type.${report.incident_type}`)}
        </Text>
      ) : null}

      {!report.server_id ? (
        <Button
          label={t('action.syncNow')}
          onPress={() => {
            void syncNow();
          }}
        />
      ) : null}
      <Button label={t('tabs.status')} variant="secondary" onPress={() => router.back()} />
    </Screen>
  );
}
