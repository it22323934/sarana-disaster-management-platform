/**
 * `/(field)/paper` — scanning a paper form back into the system.
 *
 * The lowest offline tier, and the one that decides whether a dead phone in week three
 * becomes a permanent gap in the ledger. An officer who has to stop working is a data gap
 * nobody goes back to fill, because nobody re-surveys a division that was already done.
 *
 * The screen refuses on three things and each refusal is specific, because a scanner that
 * guessed would pre-fill somebody else's household reference into a form the officer is
 * about to attest to: a code from another system, a partial scan, and a form printed for a
 * division this officer's permit does not cover.
 */

import { useRouter } from 'expo-router';
import { useState } from 'react';

import { Button, Card, Heading, Screen, Text } from '../../src/components/primitives.js';
import { TextField } from '../../src/components/TextField.js';
import { useLocale, useSession } from '../../src/providers/index.js';
import {
  decodePaperForm,
  mayTranscribe,
  type PaperFormPayload,
} from '../../src/field/paper-form.js';

export default function PaperForm() {
  const { t } = useLocale();
  const { session } = useSession();
  const router = useRouter();

  const division = session?.gnDivisionCode ?? '';
  const [scanned, setScanned] = useState('');
  const [payload, setPayload] = useState<PaperFormPayload | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  function read(value: string) {
    setScanned(value);
    if (value.trim().length === 0) {
      setPayload(null);
      setProblem(null);
      return;
    }

    try {
      const decoded = decodePaperForm(value);
      const verdict = mayTranscribe(decoded, division);
      if (!verdict.allowed) {
        // Checked at the scan, not on sync. Twenty transcriptions from a neighbouring
        // division is twenty pieces of work refused three days later.
        setPayload(null);
        setProblem(verdict.reason ?? t('field.paper.wrongDivision'));
        return;
      }
      setPayload(decoded);
      setProblem(null);
    } catch (error) {
      setPayload(null);
      setProblem(error instanceof Error ? error.message : t('field.paper.unreadable'));
    }
  }

  return (
    <Screen>
      <Heading>{t('field.paper.title')}</Heading>
      <Text muted size="sm">{t('field.paper.body')}</Text>

      {/*
        A text field beside the camera, not instead of it.
        `expo-camera` is a dependency and the scanner mounts here on a device. The typed
        field stays because a QR code that has been rained on does not always scan, and an
        officer holding a form they can read is not helped by an app that insists on the
        camera. The code is short and printed in the clear on the form for exactly this.
      */}
      <TextField
        label={t('field.paper.scan')}
        value={scanned}
        onChange={read}
        autoCapitalize="characters"
      />

      {problem ? (
        <Card>
          <Text>{problem}</Text>
        </Card>
      ) : null}

      {payload ? (
        <Card>
          <Text weight="semibold">{t('field.paper.scanned')}</Text>
          <Text size="sm">
            {t('field.paper.willPrefill', {
              reference: payload.householdReference,
              division: payload.gnDivisionCode,
            })}
          </Text>
          <Text muted size="xs">{t('field.paper.photographFormBody')}</Text>
          <Button
            label={t('field.paper.transcribe')}
            onPress={() =>
              router.push({
                pathname: '/(field)/assessments/new',
                params: {
                  reference: payload.householdReference,
                  // The record carries PAPER from here on, so an auditor six months later
                  // can see this assessment went through the paper stage.
                  source: 'PAPER',
                },
              })
            }
          />
        </Card>
      ) : null}
    </Screen>
  );
}
