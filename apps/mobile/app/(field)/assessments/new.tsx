/**
 * `/(field)/assessments/new` — the core flow, and the ninety-second budget.
 *
 * The brief: "under 90 seconds per assessment, entirely offline." Everything about this
 * screen is shaped by that number, because it is not a performance target — it is roughly
 * how long an officer will spend on a form before they start filling it in approximately,
 * and approximate assessments are what the Aid Ledger then pays against.
 *
 * What the budget buys, in order:
 *
 *   **Nothing blocks.** No network call in the interaction path, no spinner. Save writes to
 *   SQLite and returns; the sync engine catches up whenever it can.
 *
 *   **The rate is on screen while the category is chosen.** An officer who has to remember
 *   what the schedule pays is an officer who guesses, and the guess is the number.
 *
 *   **Validation is immediate and specific.** The refusal names the bound, so fixing it is
 *   one edit rather than a hunt.
 *
 *   **The provisional entitlement is shown with its working, and labelled provisional.**
 *   It catches an obvious data-entry error while the officer is still standing there. It is
 *   not the authoritative figure and the screen never lets it look like one.
 *
 * The steps are the brief's, in the brief's order, and each one is a section rather than a
 * wizard page: a wizard makes the officer wait for a transition seven times, which is most
 * of the ninety seconds.
 */

import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { View } from 'react-native';
import { formatLKR } from '@sarana/ts-shared/format';

import { Button, Card, Heading, Screen, Text } from '../../../src/components/primitives.js';
import { TextField } from '../../../src/components/TextField.js';
import { useLocale, useOffline, useSession } from '../../../src/providers/index.js';
import { SPACE } from '../../../src/theme/index.js';
import { calculate, type AssessedItem, type CostSchedule } from '../../../src/field/entitlement.js';
import {
  loadCachedSchedule,
  loadFieldContext,
  type FieldContext,
} from '../../../src/field/useFieldStore.js';
import { saveFieldAssessment, type AssessmentPhoto } from '../../../src/field/save-assessment.js';
import {
  GPS_ACCURACY_THRESHOLD_M,
  MINIMUM_PHOTOS,
  maySave,
  validateAssessment,
} from '../../../src/field/validation.js';
import type { AssessmentSource } from '../../../src/field/paper-form.js';

export default function NewAssessment() {
  const { t } = useLocale();
  const { db, log, media, refresh } = useOffline();
  const { session } = useSession();
  const router = useRouter();

  // A paper transcription arrives here with the QR's fields already decoded.
  const params = useLocalSearchParams<{
    household?: string;
    reference?: string;
    source?: string;
  }>();

  const division = session?.gnDivisionCode ?? '';
  const [schedule, setSchedule] = useState<CostSchedule | null>(null);
  const [context, setContext] = useState<FieldContext | null>(null);
  // Selected on the register screen, which navigates back here with it. There is no
  // in-screen setter: the register is the one place a household is chosen, so the form
  // cannot end up holding one the register never returned.
  const householdLocalId = params.household ?? null;
  const [items, setItems] = useState<AssessedItem[]>([]);
  const [photos, setPhotos] = useState<AssessmentPhoto[]>([]);
  const [position, setPosition] = useState<{
    latitude: number | null;
    longitude: number | null;
    accuracy: number | null;
    source: 'GPS' | 'MANUAL' | null;
  }>({ latitude: null, longitude: null, accuracy: null, source: null });
  const [saving, setSaving] = useState(false);
  const source: AssessmentSource = params.source === 'PAPER' ? 'PAPER' : 'PHONE';

  useEffect(() => {
    if (!db) return;
    void loadCachedSchedule(db).then(setSchedule);
    void loadFieldContext(db).then(setContext);
  }, [db]);

  const problems = useMemo(() => {
    if (!schedule) return [];
    return validateAssessment(
      {
        householdLocalId,
        items,
        photoCount: photos.length,
        latitude: position.latitude,
        longitude: position.longitude,
        gpsAccuracyM: position.accuracy,
        locationSource: position.source,
      },
      { schedule, now: Date.now(), division },
    );
  }, [schedule, householdLocalId, items, photos.length, position, division]);

  // Recomputed on every change, because the whole value of an on-device figure is that it
  // moves while the officer is looking at it. It is pure arithmetic over a cached schedule,
  // so there is nothing to debounce.
  const trace = useMemo(() => {
    if (!schedule || items.length === 0) return null;
    try {
      return calculate(items, schedule);
    } catch {
      // A category the cached schedule cannot price. The validator has already said so in
      // terms the officer can act on; showing a broken figure as well would add noise.
      return null;
    }
  }, [schedule, items]);

  async function save() {
    // The hazard event is required by the schema and there is no default for it. A form
    // that saved without one would produce a row the server refuses three days later.
    if (!db || !log || !media || !schedule || !householdLocalId || saving) return;
    if (!context?.hazard_event_id) return;
    setSaving(true);
    try {
      const household = await db.select<{ server_id: string | null; gn_division_id: string }>(
        'SELECT server_id, gn_division_id FROM household WHERE local_id = ?',
        [householdLocalId],
      );

      await saveFieldAssessment(
        { log, media, schedule },
        {
          householdId: household[0]?.server_id ?? householdLocalId,
          householdLocalId,
          gnDivisionId: household[0]?.gn_division_id ?? context.gn_division_id,
          gnDivisionCode: division,
          hazardEventId: context.hazard_event_id,
          items,
          photos,
          latitude: position.latitude!,
          longitude: position.longitude!,
          gpsAccuracyM: position.accuracy,
          locationSource: position.source!,
          source,
        },
        { division },
      );

      refresh();
      // Straight back to a blank form. The officer is walking to the next house and the
      // brief's pace is 30 to 60 of these in a day; a confirmation screen they have to
      // dismiss is sixty taps nobody budgeted for.
      router.replace('/(field)/assessments/new');
    } finally {
      setSaving(false);
    }
  }

  // Two things this device must have been given before an assessment can exist at all:
  // a schedule to price against and an event to file under. Neither has a safe default.
  if (!schedule || !context?.hazard_event_id) {
    return (
      <Screen>
        <Heading>{t('field.assessment.title')}</Heading>
        <Card>
          {/* Never a default schedule and never an invented hazard event. An officer
              pricing damage against a made-up rate would produce figures nobody can
              reproduce, and would not know. The paper tier is the honest fallback. */}
          <Text weight="semibold">{t('field.assessment.notReady')}</Text>
          <Text muted size="sm">{t('field.assessment.notReadyBody')}</Text>
        </Card>
      </Screen>
    );
  }

  return (
    <Screen>
      <Heading>{t('field.assessment.title')}</Heading>
      {source === 'PAPER' ? (
        <Text muted size="sm">{t('field.assessment.sourcePaper')}</Text>
      ) : null}

      <Card>
        <Text weight="semibold">{t('field.assessment.step1')}</Text>
        {householdLocalId ? (
          <>
            <Text size="sm">{params.reference ?? householdLocalId}</Text>
            <Button
              label={t('field.assessment.changeHousehold')}
              variant="secondary"
              onPress={() => router.push('/(field)/households')}
            />
          </>
        ) : (
          <Button
            label={t('field.assessment.selectHousehold')}
            onPress={() => router.push('/(field)/households')}
          />
        )}
      </Card>

      <Card>
        <Text weight="semibold">{t('field.assessment.step2')}</Text>
        {items.map((item, index) => {
          const line = schedule.lines[item.category];
          return (
            <View key={`${item.category}-${index}`} style={{ gap: SPACE[1] }}>
              <Text weight="medium">{item.category}</Text>
              {/* The rate, on screen, while the category is being chosen. */}
              {line ? (
                <Text muted size="xs">
                  {t('field.assessment.rate', { amount: formatLKR(line.unit_amount_cents) })} ·{' '}
                  {t('field.assessment.cap', { count: line.max_units })}
                </Text>
              ) : null}
              <TextField
                label={t('field.assessment.units')}
                value={String(item.units)}
                keyboardType="number-pad"
                onChange={(next) =>
                  setItems((current) =>
                    current.map((entry, position) =>
                      position === index
                        ? { ...entry, units: Number.parseInt(next, 10) || 0 }
                        : entry,
                    ),
                  )
                }
              />
              <Button
                label={t('field.assessment.removeCategory')}
                variant="secondary"
                onPress={() =>
                  setItems((current) => current.filter((_, position) => position !== index))
                }
              />
            </View>
          );
        })}

        {Object.keys(schedule.lines)
          .filter((category) => !items.some((item) => item.category === category))
          .map((category) => (
            <Button
              key={category}
              label={category}
              variant="secondary"
              onPress={() => setItems((current) => [...current, { category, units: 1 }])}
            />
          ))}
      </Card>

      <Card>
        <Text weight="semibold">{t('field.assessment.step3')}</Text>
        <Text size="sm">
          {t('field.assessment.photosTaken', { count: photos.length, required: MINIMUM_PHOTOS })}
        </Text>
        <Text muted size="xs">{t('field.assessment.photoGuidance')}</Text>
        <Button
          label={t('field.assessment.takeWide')}
          variant="secondary"
          onPress={() =>
            setPhotos((current) => [
              ...current,
              {
                localUri: `file:///pending/${Date.now()}-wide.jpg`,
                contentType: 'image/jpeg',
                sizeBytes: 0,
                kind: 'wide',
              },
            ])
          }
        />
        <Button
          label={t('field.assessment.takeDetail')}
          variant="secondary"
          onPress={() =>
            setPhotos((current) => [
              ...current,
              {
                localUri: `file:///pending/${Date.now()}-detail.jpg`,
                contentType: 'image/jpeg',
                sizeBytes: 0,
                kind: 'detail',
              },
            ])
          }
        />
      </Card>

      <Card>
        <Text weight="semibold">{t('field.assessment.step4')}</Text>
        {position.source === null ? (
          <Text size="sm">{t('field.assessment.gpsWaiting')}</Text>
        ) : (
          <>
            <Text size="sm">
              {position.source === 'GPS'
                ? t('field.assessment.gpsAccuracy', { metres: Math.round(position.accuracy ?? 0) })
                : t('field.assessment.usingManualPin')}
            </Text>
            {position.source === 'GPS' && (position.accuracy ?? 0) > GPS_ACCURACY_THRESHOLD_M ? (
              <Text size="sm">{t('field.assessment.gpsPoor')}</Text>
            ) : null}
          </>
        )}
        <Button
          label={t('field.assessment.placePin')}
          variant="secondary"
          onPress={() =>
            setPosition((current) => ({ ...current, source: 'MANUAL', accuracy: null }))
          }
        />
      </Card>

      {trace ? (
        <Card>
          <Text weight="semibold">{t('field.assessment.step5')}</Text>
          <Text size="lg" weight="semibold">{formatLKR(trace.result_lkr_cents)}</Text>
          {/* Provisional, said twice: once as a heading and once as a sentence explaining
              who recalculates and whose figure is paid. */}
          <Text weight="medium">{t('field.assessment.provisionalTitle')}</Text>
          <Text muted size="xs">
            {t('field.assessment.provisionalBody', { version: schedule.version })}
          </Text>

          <Text weight="medium" size="sm">{t('field.assessment.workingTitle')}</Text>
          {trace.steps.map((step) => (
            <Text key={step.description} muted size="xs">
              {step.description}: {formatLKR(step.result_cents)}
            </Text>
          ))}
          {trace.caps_applied.map((cap) => (
            <Text key={cap} size="xs">{cap}</Text>
          ))}
        </Card>
      ) : null}

      {problems.length > 0 ? (
        <Card>
          <Text weight="semibold">{t('field.assessment.cannotSave')}</Text>
          {problems.map((problem) => (
            <Text key={`${problem.field}-${problem.message}`} size="sm">
              {problem.message}
            </Text>
          ))}
        </Card>
      ) : null}

      <Button
        label={t('field.assessment.save')}
        onPress={save}
        disabled={!maySave(problems) || saving}
      />
    </Screen>
  );
}
