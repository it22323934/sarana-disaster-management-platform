/**
 * `sarana://debug?action=...` - the surface the offline e2e suite drives.
 *
 * Present only in a development build. In a production bundle `runDebugAction` refuses
 * before it looks at the action, and this screen renders the refusal - so the route
 * exists in the bundle and does nothing, rather than being conditionally compiled out and
 * silently 404ing during a test run against the wrong build.
 *
 * The result is rendered as text because that is what Maestro can read. There is no API
 * here, no port listening, nothing reachable from off the device.
 */

import { useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';

import { Card, Heading, Screen, Text } from '../src/components/primitives.js';
import { DEBUG_ENABLED, runDebugAction } from '../src/debug/bridge.js';
import { useOffline } from '../src/providers/index.js';
import { saveAssessmentDraft, SAMPLE_DRAFT } from '../src/field/assessment-draft.js';

export default function DebugScreen() {
  const params = useLocalSearchParams<Record<string, string>>();
  const { db, log, refresh } = useOffline();
  const [result, setResult] = useState('running');

  useEffect(() => {
    if (!db || !log) return;
    void (async () => {
      const outcome = await runDebugAction(
        { action: String(params.action ?? ''), params: params as Record<string, string> },
        {
          db,
          log,
          saveAssessment: () => saveAssessmentDraft(log, SAMPLE_DRAFT),
        },
      );
      setResult(`${outcome.ok ? 'ok' : 'refused'}: ${outcome.detail}`);
      refresh();
    })();
  }, [db, log, params, refresh]);

  return (
    <Screen>
      <Heading>Debug bridge</Heading>
      <Card>
        {/* Maestro reads this line. Keeping it a single, stable string is the contract. */}
        <Text>{DEBUG_ENABLED ? result : 'refused: not a development build'}</Text>
      </Card>
    </Screen>
  );
}
