/**
 * One entitlement, with the working shown.
 *
 * The same trace the ops console renders for an officer, rendered for the household. Not
 * simplified - **checkable**. Every figure comes out of `calculation_trace` exactly as the
 * ledger wrote it, the schedule version is on screen, and there is a link to the published
 * rates so a household can look up the number themselves rather than take this screen's
 * word for it.
 *
 * A trace with no steps is not padded out with a plausible sentence. The amount is shown,
 * the absence is stated, and raising a grievance about it is one tap - because "the
 * platform cannot show you how it got this number" is exactly the kind of thing a
 * grievance exists for.
 */

import { useLocalSearchParams, useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { View } from 'react-native';

import { Button, Card, Heading, Screen, Text } from '../../../../src/components/primitives.js';
import {
  explain,
  isExplainable,
  type CalculationTrace,
} from '../../../../src/citizen/entitlement-explanation.js';
import { useLocale, useSession } from '../../../../src/providers/index.js';
import { SPACE } from '../../../../src/theme/index.js';

interface EntitlementDetail {
  readonly id: string;
  readonly assessment_ref: string;
  readonly calculated_lkr_cents: number;
  readonly calculation_trace: CalculationTrace | null;
  readonly cost_schedule_version: string;
  readonly status: string;
}

export default function EntitlementScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useLocale();
  const { client } = useSession();
  const router = useRouter();

  const entitlement = useQuery({
    queryKey: ['entitlement', id],
    enabled: Boolean(id),
    queryFn: () => client.get(`/api/v1/entitlements/${id}`) as Promise<EntitlementDetail>,
  });

  const data = entitlement.data;
  if (!data) return <Screen />;

  const trace = data.calculation_trace;
  const explanation = isExplainable(trace) ? explain(trace) : null;

  return (
    <Screen>
      <Heading>{t('aid.entitlement')}</Heading>

      <Card>
        <Text size="2xl" weight="semibold">
          {explanation?.total ??
            new Intl.NumberFormat('en-LK', { minimumFractionDigits: 2 }).format(
              data.calculated_lkr_cents / 100,
            )}
        </Text>
        <Text size="sm" muted>
          {t('aid.entitlementStatus', { status: data.status })}
        </Text>
      </Card>

      <Text weight="semibold">{t('aid.explain.title')}</Text>

      {explanation === null ? (
        <Card>
          <Text>{t('aid.explain.unavailable')}</Text>
        </Card>
      ) : (
        <Card>
          {explanation.lines.map((line, index) => (
            <View key={`${line.messageKey}-${index}`} style={{ gap: SPACE[1] }}>
              <Text size="sm">{t(line.messageKey, line.values)}</Text>
              {line.expression ? (
                // Shown as the ledger wrote it. A household checking a figure needs the
                // arithmetic, not a paraphrase of it.
                <Text size="xs" muted>
                  {line.expression}
                </Text>
              ) : null}
              {line.amount ? <Text weight="medium">{line.amount}</Text> : null}
            </View>
          ))}
          <View style={{ gap: SPACE[1], paddingTop: SPACE[2] }}>
            <Text size="sm" muted>
              {t('aid.explain.total')}
            </Text>
            <Text size="xl" weight="semibold">
              {explanation.total}
            </Text>
          </View>
        </Card>
      )}

      <Button
        label={t('aid.explain.openSchedule')}
        variant="secondary"
        onPress={() => router.push(`/(citizen)/aid/schedule?version=${data.cost_schedule_version}`)}
      />
      <Button
        label={t('aid.grievanceOpen')}
        variant="secondary"
        onPress={() => router.push(`/(citizen)/aid/grievance/new?subject=ENTITLEMENT&id=${data.id}`)}
      />
    </Screen>
  );
}
