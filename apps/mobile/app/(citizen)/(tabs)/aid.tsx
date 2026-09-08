/**
 * Aid: where the transparency promise reaches the person it is actually for.
 *
 * The recovery path, three months after the emergency path. Different emotional state,
 * different design: patience rather than panic, so this screen is allowed to be a list of
 * things to read carefully, and it is allowed to load.
 *
 * The order is the order money moves in - what was recorded, what it came to, what was
 * paid - because that is the order a household needs it in to spot the step that went
 * wrong. And every one of those steps has a grievance route off it, presented as a right
 * rather than as a support link.
 */

import { useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { Pressable, View } from 'react-native';
import { formatLKR } from '@sarana/ts-shared/format';

import { Button, Card, Heading, Screen, Text } from '../../../src/components/primitives.js';
import { useLocale, useSession } from '../../../src/providers/index.js';
import { SPACE, touchTarget } from '../../../src/theme/index.js';

interface AssessmentSummary {
  readonly id: string;
  readonly public_ref: string;
  readonly category: string;
  readonly assessed_at: string;
  readonly cost_estimate_lkr_cents: number;
  readonly status: string;
}

interface EntitlementSummary {
  readonly id: string;
  readonly assessment_ref: string;
  readonly calculated_lkr_cents: number;
  readonly status: string;
  readonly released: boolean;
}

interface DisbursementSummary {
  readonly id: string;
  readonly reference: string;
  readonly amount_lkr_cents: number;
  readonly status: string;
  readonly rail: string;
  readonly released_at: string | null;
}

export default function AidTab() {
  const { t, locale } = useLocale();
  const { client, session } = useSession();
  const router = useRouter();
  const household = session?.householdId ?? null;

  const assessments = useQuery({
    queryKey: ['assessments', household, locale],
    enabled: household !== null,
    queryFn: () => client.get('/api/v1/assessments', { query: { limit: 20 } }) as Promise<AssessmentSummary[]>,
  });

  const entitlements = useQuery({
    queryKey: ['entitlements', household, locale],
    enabled: household !== null,
    queryFn: () => client.get('/api/v1/entitlements', { query: { limit: 20 } }) as Promise<EntitlementSummary[]>,
  });

  const disbursements = useQuery({
    queryKey: ['disbursements', household, locale],
    enabled: household !== null,
    queryFn: () => client.get('/api/v1/disbursements', { query: { limit: 20 } }) as Promise<DisbursementSummary[]>,
  });

  return (
    <Screen>
      <Heading>{t('tabs.aid')}</Heading>

      {household === null ? (
        <Card>
          <Text weight="medium">{t('onboarding.householdTitle')}</Text>
          <Text size="sm" muted>
            {t('onboarding.householdWhy')}
          </Text>
          <Button
            label={t('onboarding.householdTitle')}
            onPress={() => router.push('/(onboarding)/household')}
          />
        </Card>
      ) : null}

      <View style={{ gap: SPACE[2] }}>
        <Text weight="semibold">{t('aid.assessments')}</Text>
        {(assessments.data ?? []).length === 0 ? (
          <Text size="sm" muted>
            {t('aid.assessmentNone')}
          </Text>
        ) : (
          (assessments.data ?? []).map((assessment) => (
            <Card key={assessment.id}>
              <Text>{t('aid.assessmentCategory', { category: assessment.category })}</Text>
              <Text size="sm" muted>
                {t('aid.assessmentBy', { when: assessment.assessed_at.slice(0, 10) })}
              </Text>
              <Text size="sm">{formatLKR(assessment.cost_estimate_lkr_cents)}</Text>
              <Pressable
                onPress={() =>
                  router.push(
                    `/(citizen)/aid/grievance/new?subject=ASSESSMENT&id=${assessment.id}`,
                  )
                }
                accessibilityRole="button"
                style={{ minHeight: touchTarget('min'), justifyContent: 'center' }}
              >
                <Text size="sm" colour="#0E7C86">
                  {t('aid.grievanceOpen')}
                </Text>
              </Pressable>
            </Card>
          ))
        )}
      </View>

      <View style={{ gap: SPACE[2] }}>
        <Text weight="semibold">{t('aid.entitlement')}</Text>
        {(entitlements.data ?? []).length === 0 ? (
          <Text size="sm" muted>
            {t('aid.entitlementNone')}
          </Text>
        ) : (
          (entitlements.data ?? []).map((entitlement) => (
            <Pressable
              key={entitlement.id}
              onPress={() => router.push(`/(citizen)/aid/entitlements/${entitlement.id}`)}
              accessibilityRole="button"
            >
              <Card>
                <Text size="lg" weight="semibold">
                  {formatLKR(entitlement.calculated_lkr_cents)}
                </Text>
                <Text size="sm" muted>
                  {t('aid.entitlementStatus', { status: entitlement.status })}
                </Text>
                <Text size="sm" colour="#0E7C86">
                  {t('aid.explain.title')}
                </Text>
              </Card>
            </Pressable>
          ))
        )}
      </View>

      <View style={{ gap: SPACE[2] }}>
        <Text weight="semibold">{t('aid.disbursement')}</Text>
        {(disbursements.data ?? []).length === 0 ? (
          <Text size="sm" muted>
            {t('aid.disbursementNone')}
          </Text>
        ) : (
          (disbursements.data ?? []).map((disbursement) => (
            <Card key={disbursement.id}>
              <Text size="lg" weight="semibold">
                {formatLKR(disbursement.amount_lkr_cents)}
              </Text>
              {disbursement.released_at ? (
                <Text size="sm" muted>
                  {t('aid.disbursementSent', {
                    when: disbursement.released_at.slice(0, 10),
                    rail: disbursement.rail,
                  })}
                </Text>
              ) : null}
              <Text size="xs" muted>
                {t('aid.disbursementRef', { reference: disbursement.reference })}
              </Text>

              {/* The confirmation loop, mirroring the SMS one. "No" opens the grievance
                  flow pre-filled: a household that says the money did not arrive should not
                  then have to find a form. */}
              <Text size="sm" weight="medium">
                {t('aid.confirmTitle')}
              </Text>
              <View style={{ flexDirection: 'row', gap: SPACE[2] }}>
                <View style={{ flex: 1 }}>
                  <Button
                    label={t('aid.confirmYes')}
                    onPress={() => {
                      void client.post(`/api/v1/disbursements/${disbursement.id}/confirm`, {
                        body: { received: true },
                        idempotencyKey: `confirm-${disbursement.id}`,
                      });
                    }}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Button
                    label={t('aid.confirmNo')}
                    variant="secondary"
                    onPress={() =>
                      router.push(
                        `/(citizen)/aid/grievance/new?subject=DISBURSEMENT&id=${disbursement.id}&reason=notReceived`,
                      )
                    }
                  />
                </View>
              </View>
            </Card>
          ))
        )}
      </View>
    </Screen>
  );
}
