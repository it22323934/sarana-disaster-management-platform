/**
 * `/(field)/assessments` — every assessment on this device, fully offline.
 *
 * Reads `assessment` directly rather than through a query hook. That is the point of the
 * screen: it is the officer's record of their own day and it must render on a device that
 * has not seen a tower since Tuesday. Anything that could fall back to a network request
 * would eventually be the thing that fails at the wrong moment.
 *
 * Sync state is shown per row because the officer is the one who has to notice a record
 * that is stuck, and the alternative — a single count at the top — hides which one.
 */

import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';
import { formatLKR } from '@sarana/ts-shared/format';

import { Card, Heading, Screen, Text } from '../../../src/components/primitives.js';
import { useLocale, useOffline } from '../../../src/providers/index.js';
import { SPACE } from '../../../src/theme/index.js';

interface Row {
  readonly local_id: string;
  readonly category: string;
  readonly cost_estimate_lkr_cents: number;
  readonly assessed_at: string;
  readonly source: string;
  readonly status: string;
  readonly sync_status: string | null;
}

export default function AssessmentList() {
  const { t } = useLocale();
  const { db, counts } = useOffline();
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    if (!db) return;
    let cancelled = false;

    void (async () => {
      // Left join to the operation log so each row can say whether it has reached the
      // office. One query, because this list is read on every return from the form.
      const found = await db.select<Row>(
        'SELECT a.local_id, a.category, a.cost_estimate_lkr_cents, a.assessed_at, a.source, ' +
          'a.status, o.status AS sync_status ' +
          'FROM assessment a ' +
          'LEFT JOIN operation_log o ON o.entity_local_id = a.local_id ' +
          'ORDER BY a.assessed_at DESC LIMIT 200',
      );
      if (!cancelled) setRows(found);
    })();

    return () => {
      cancelled = true;
    };
  }, [db, counts]);

  return (
    <Screen>
      <Heading>{t('field.assessment.listTitle')}</Heading>

      {rows.length === 0 ? (
        <Text muted>{t('field.assessment.empty')}</Text>
      ) : (
        rows.map((row) => (
          <Pressable
            key={row.local_id}
            onPress={() => router.push(`/(field)/assessments/${row.local_id}`)}
            accessibilityRole="button"
          >
            <Card>
              <View style={{ gap: SPACE[1] }}>
                <Text weight="medium">{row.category}</Text>
                <Text size="sm">{formatLKR(row.cost_estimate_lkr_cents)}</Text>
                <Text muted size="xs">
                  {new Date(row.assessed_at).toLocaleString()}
                  {row.source === 'PAPER' ? ` · ${t('field.assessment.sourcePaper')}` : ''}
                </Text>
                {/* Per row, not per screen: a single count at the top hides which record
                    is the one that is stuck. */}
                <Text muted size="xs">
                  {row.sync_status === 'synced'
                    ? t('sync.status.allSynced')
                    : t('sync.detail.queued', { count: 1 })}
                </Text>
              </View>
            </Card>
          </Pressable>
        ))
      )}
    </Screen>
  );
}
