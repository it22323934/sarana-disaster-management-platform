/**
 * The published cost schedule, so a household can check the rate themselves.
 *
 * The entitlement screen shows the working. This is the other half of making that working
 * checkable: the rates it was worked out against, at the version that was pinned, in the
 * household's own language. Without this the explanation asks them to take the app's word
 * for the number, which is the opacity the whole transparency chain exists to remove.
 *
 * `GET /api/v1/cost-schedules` is a read the platform already publishes.
 */

import { useLocalSearchParams } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { formatLKR } from '@sarana/ts-shared/format';

import { Card, Heading, Screen, Text } from '../../../src/components/primitives.js';
import { useLocale, useSession } from '../../../src/providers/index.js';

interface ScheduleLine {
  readonly category: string;
  readonly unit_amount_lkr_cents: number;
  readonly unit_label: string;
}

interface Schedule {
  readonly version: string;
  readonly published_at: string | null;
  readonly household_cap_lkr_cents: number;
  readonly lines: readonly ScheduleLine[];
}

export default function ScheduleScreen() {
  const { version } = useLocalSearchParams<{ version?: string }>();
  const { t } = useLocale();
  const { client } = useSession();

  const schedules = useQuery({
    queryKey: ['cost-schedules'],
    queryFn: () => client.get('/api/v1/cost-schedules') as Promise<Schedule[]>,
  });

  // The pinned version, not the newest. An entitlement is valued against the schedule that
  // was in force on the assessment date, and showing a later one would explain a number
  // nobody calculated.
  const schedule =
    (schedules.data ?? []).find((entry) => entry.version === version) ?? schedules.data?.[0];

  if (!schedule) return <Screen />;

  return (
    <Screen>
      <Heading>{t('aid.explain.openSchedule')}</Heading>
      <Text size="sm" muted>
        {t('aid.explain.schedule', { version: schedule.version })}
      </Text>

      {schedule.lines.map((line) => (
        <Card key={line.category}>
          <Text weight="medium">{line.category}</Text>
          <Text>{formatLKR(line.unit_amount_lkr_cents)}</Text>
          <Text size="xs" muted>
            {line.unit_label}
          </Text>
        </Card>
      ))}

      <Card>
        <Text size="sm" muted>
          {t('aid.explain.capped', { caps: 'household_cap' })}
        </Text>
        <Text>{formatLKR(schedule.household_cap_lkr_cents)}</Text>
      </Card>
    </Screen>
  );
}
