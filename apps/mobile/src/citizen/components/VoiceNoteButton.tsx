/**
 * The voice note, and why it is the biggest control on the report screen.
 *
 * Typing Sinhala or Tamil on a phone keyboard is slow at the best of times and much
 * slower with wet hands in poor light. Speaking is not. Voice is also the only input on
 * this screen that works for someone who cannot write in their own script, which is not a
 * small population and is not one the platform gets to design around.
 *
 * Hold to record, release to stop - one gesture, no mode to get stuck in. A tap-to-start
 * button leaves a panicking person recording thirty seconds of nothing because they did
 * not see it was still going.
 */

import { useAudioRecorder, AudioModule, RecordingPresets, setAudioModeAsync } from 'expo-audio';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Text, useSurface } from '../../components/primitives.js';
import { useLocale } from '../../providers/LocaleProvider.js';
import { RADIUS, SPACE, fontScale, touchTarget } from '../../theme/index.js';

/**
 * The cap incident-svc enforces at presign.
 *
 * Mirrored here so the recording stops at thirty seconds rather than being refused after
 * the person has finished speaking - which would be the second time this platform told
 * somebody their evidence was too big only after they had spent the effort.
 */
export const MAX_SECONDS = 30;

export interface VoiceNoteButtonProps {
  readonly uri: string | null;
  readonly onRecorded: (uri: string | null) => void;
}

export function VoiceNoteButton({ uri, onRecorded }: VoiceNoteButtonProps) {
  const { t } = useLocale();
  const surface = useSurface();
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const [seconds, setSeconds] = useState(0);
  const [denied, setDenied] = useState(false);
  const ticker = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (ticker.current) clearInterval(ticker.current);
    };
  }, []);

  const stop = useCallback(async () => {
    if (ticker.current) {
      clearInterval(ticker.current);
      ticker.current = null;
    }
    setSeconds(0);
    await recorder.stop();
    onRecorded(recorder.uri ?? null);
  }, [onRecorded, recorder]);

  const start = useCallback(async () => {
    const permission = await AudioModule.requestRecordingPermissionsAsync();
    if (!permission.granted) {
      // Named, not silent. A hold that does nothing reads as a broken app, and the person
      // tries again instead of typing.
      setDenied(true);
      return;
    }
    setDenied(false);
    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    recorder.record();

    ticker.current = setInterval(() => {
      setSeconds((elapsed) => {
        const next = elapsed + 1;
        // Stops itself at the server's limit rather than recording something that will be
        // refused at presign.
        if (next >= MAX_SECONDS) void stop();
        return next;
      });
    }, 1000);
  }, [recorder, stop]);

  const recording = seconds > 0;
  const size = Math.max(touchTarget('sos') * 1.6, 96 * fontScale());

  return (
    <View style={{ alignItems: 'center', gap: SPACE[2] }}>
      <Pressable
        onPressIn={() => void start()}
        onPressOut={() => void stop()}
        accessibilityRole="button"
        accessibilityLabel={t('report.voiceNote')}
        accessibilityHint={t('report.voiceHint')}
        style={[
          styles.button,
          {
            width: size,
            height: size,
            borderRadius: size / 2,
            backgroundColor: recording ? '#DC2626' : uri ? '#2F6F4E' : '#0E7C86',
          },
        ]}
      >
        <Text colour="#FFFFFF" weight="semibold" align="center" size="sm">
          {recording ? t('report.recording', { seconds }) : uri ? '✓' : t('report.voiceNote')}
        </Text>
      </Pressable>
      <Text size="xs" muted align="center">
        {denied ? t('permission.microphone.why') : t('report.voiceHint')}
      </Text>
      {uri ? (
        <Pressable
          onPress={() => onRecorded(null)}
          accessibilityRole="button"
          accessibilityLabel={t('action.cancel')}
          style={{ minHeight: touchTarget('min'), justifyContent: 'center' }}
        >
          <Text size="sm" colour={surface.muted}>
            {t('action.cancel')}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  button: { alignItems: 'center', justifyContent: 'center', padding: SPACE[2] },
});
