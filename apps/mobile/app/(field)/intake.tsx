/**
 * `/(field)/intake` — a report taken on behalf of someone with no phone or no signal.
 *
 * The same flow as the citizen report (file 23) with two additions the brief names: who is
 * reporting, and an "on behalf of" marker so the incident record shows the report came
 * through an officer rather than from the person themselves.
 *
 * **The trust weighting is stated on the screen.** Officer-reported incidents carry higher
 * default confidence in verification (file 15), and that is a documented scoring input, not
 * a hidden one. An officer should know that filing on somebody's behalf moves their report
 * up the queue relative to an anonymous one — both because it is true and because a
 * weighting nobody is told about is a weighting nobody can challenge.
 *
 * The reporter's own details go into the report payload and nowhere near a log: they are a
 * name and a phone number, which is exactly what `field/safe-log.ts` exists to keep out of
 * logcat.
 */

import { useRouter } from 'expo-router';
import { useState } from 'react';

import { Button, Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { TextField } from '../../src/components/TextField.js';
import { useLocale, useOffline, useSession } from '../../src/providers/index.js';
import { saveOfficerReport } from '../../src/field/officer-report.js';

export default function Intake() {
  const { t, locale } = useLocale();
  const { log, refresh } = useOffline();
  const { session } = useSession();
  const router = useRouter();

  const [reporterName, setReporterName] = useState('');
  const [reporterContact, setReporterContact] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (!log || saving) return;
    setSaving(true);
    try {
      await saveOfficerReport(log, {
        incidentType: null,
        text: description.trim() || null,
        language: locale,
        location: null,
        peopleAtRisk: null,
        reporterName: reporterName.trim() || null,
        reporterContact: reporterContact.trim() || null,
        // Required. The higher verification confidence these reports carry rests on a
        // named civil servant having been there, so the record has to name them.
        reportedBy: session?.subjectId ?? '',
      });
      refresh();
      router.replace('/(field)');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Screen>
      <Heading>{t('field.intake.title')}</Heading>
      <Text muted size="sm">{t('field.intake.body')}</Text>

      <TextField
        label={t('field.intake.reporterName')}
        value={reporterName}
        onChange={setReporterName}
      />
      <TextField
        label={t('field.intake.reporterContact')}
        value={reporterContact}
        onChange={setReporterContact}
        keyboardType="phone-pad"
      />
      <TextField
        label={t('report.describe')}
        value={description}
        onChange={setDescription}
        multiline
      />

      <Card>
        <Text size="sm">{t('field.intake.onBehalf')}</Text>
        {/* Documented, not hidden. A weighting nobody is told about cannot be challenged. */}
        <Text muted size="xs">{t('field.intake.trustNote')}</Text>
      </Card>

      <Button label={t('field.intake.submit')} onPress={submit} disabled={saving} />
    </Screen>
  );
}
