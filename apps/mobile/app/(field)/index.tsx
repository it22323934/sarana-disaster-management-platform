/**
 * The Field Companion home: what is waiting, what is on this device, and the way in.
 *
 * The brief's `/(field)/home` — "today: queued syncs, assigned work, active alerts". The
 * ordering is deliberate and it is not the brief's: **the offline permit comes first.**
 *
 * It is the credential the whole surface depends on, and an officer needs to know it is
 * valid *before* they walk into a division with no signal. Finding out three days later
 * that every assessment will be refused is finding out after the work is unrepeatable.
 *
 * The evidence note at the bottom is the framing the brief asks for and it is load-bearing
 * rather than decorative: an officer who believes the app is watching them will find ways
 * not to use it, and a Field Companion nobody uses leaves the Aid Ledger with no input.
 */

import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';

import { capabilityStatus } from '../../src/auth/capability.js';
import { Button, Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { useLocale, useOffline, useSession } from '../../src/providers/index.js';

export default function FieldHome() {
  const { t } = useLocale();
  const { counts, db } = useOffline();
  const { session, capability, setSurface } = useSession();
  const router = useRouter();

  const division = session?.gnDivisionCode ?? '';
  const status = capabilityStatus(capability, { division, now: Date.now() });

  const [households, setHouseholds] = useState<{ total: number; provisional: number } | null>(null);
  const [today, setToday] = useState(0);

  useEffect(() => {
    if (!db) return;
    let cancelled = false;

    void (async () => {
      const [registry] = await db.select<{ total: number; provisional: number }>(
        'SELECT COUNT(*) AS total, ' +
          'COALESCE(SUM(CASE WHEN is_provisional = 1 THEN 1 ELSE 0 END), 0) AS provisional ' +
          'FROM household WHERE gn_division_code = ?',
        [division],
      );
      // Colombo local midnight, which is what "today" means to the officer walking the
      // division - not UTC, which would roll over at half past five in the morning.
      const since = new Date();
      since.setHours(0, 0, 0, 0);
      const [recorded] = await db.select<{ count: number }>(
        'SELECT COUNT(*) AS count FROM assessment WHERE assessed_at >= ?',
        [since.toISOString()],
      );

      if (cancelled) return;
      setHouseholds(registry ?? { total: 0, provisional: 0 });
      setToday(recorded?.count ?? 0);
    })();

    return () => {
      cancelled = true;
    };
  }, [db, division, counts]);

  const queued = counts.pending + counts.syncing + counts.blocked;

  return (
    <Screen>
      <Heading>{t('field.home.title')}</Heading>
      <Text muted size="sm">{t('field.home.division', { code: division })}</Text>

      {/* First, because it is the thing that has to be true before any of the rest matters. */}
      <Card>
        <Text weight="semibold">{t('auth.capability.title')}</Text>
        {status.usable ? (
          <Text size="sm">
            {t('auth.capability.held', {
              hours: Math.floor(status.expiresInMs / 3_600_000),
              division,
            })}
          </Text>
        ) : (
          <Text size="sm">
            {status.reason === 'expired'
              ? t('auth.capability.expired')
              : status.reason === 'wrong-division'
                ? t('auth.capability.wrongDivision', {
                    held: capability?.gnDivisionCode ?? '',
                    asked: division,
                  })
                : t('auth.capability.absent')}
          </Text>
        )}
        <Text muted size="xs">{t('auth.capability.explains')}</Text>
      </Card>

      <Card>
        <Text weight="semibold">
          {queued > 0 ? t('field.home.queued', { count: queued }) : t('field.home.allSynced')}
        </Text>
        <Text size="sm">{t('field.home.assessmentsToday', { count: today })}</Text>
        {households ? (
          <>
            <Text size="sm">{t('field.home.households', { count: households.total })}</Text>
            {households.provisional > 0 ? (
              <Text muted size="xs">
                {t('field.home.provisional', { count: households.provisional })}
              </Text>
            ) : null}
          </>
        ) : null}
      </Card>

      <Button label={t('field.home.startAssessment')} onPress={() => router.push('/(field)/assessments/new')} />
      <Button
        label={t('field.home.scanPaper')}
        variant="secondary"
        onPress={() => router.push('/(field)/paper')}
      />
      <Button
        label={t('field.home.openIntake')}
        variant="secondary"
        onPress={() => router.push('/(field)/intake')}
      />
      <Button
        label={t('field.home.openRegister')}
        variant="secondary"
        onPress={() => router.push('/(field)/households')}
      />
      <Button
        label={t('field.assessment.listTitle')}
        variant="secondary"
        onPress={() => router.push('/(field)/assessments')}
      />
      <Button
        label={t('field.home.openDivision')}
        variant="secondary"
        onPress={() => router.push('/(field)/division')}
      />
      <Button
        label={t('field.home.openSync')}
        variant="secondary"
        onPress={() => router.push('/(field)/sync')}
      />

      <Card>
        {/* The framing the brief asks for, in the officer's own terms. */}
        <Text size="sm">{t('field.home.evidenceNote')}</Text>
      </Card>

      <Button
        label="Citizen app"
        variant="secondary"
        onPress={() => {
          setSurface('citizen');
          router.replace('/(citizen)/(tabs)/home');
        }}
      />
    </Screen>
  );
}
