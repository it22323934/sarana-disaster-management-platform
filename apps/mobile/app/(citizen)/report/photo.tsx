/**
 * Taking a photo, behind the storage guard.
 *
 * The guard runs **before the camera opens**, not after the shutter. The failure it
 * prevents is specific and has happened to every field app ever built: the device fills
 * up, the camera returns a zero-byte file, the form saves happily, and forty reports turn
 * out to have no photographs.
 *
 * Compression happens here rather than at upload, for the same reason: a 4MB original is
 * 4MB of a citizen's storage and their data allowance, and 1600px at quality 0.7 is
 * everything a responder needs to see whether a wall is down.
 */

import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImageManipulator from 'expo-image-manipulator';
import { useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Button, Card, Heading, Screen, Text } from '../../../src/components/primitives.js';
import { storageVerdict } from '../../../src/offline/storage/device-storage.js';
import { useLocale, useOffline } from '../../../src/providers/index.js';
import { ACCENT, SPACE, touchTarget } from '../../../src/theme/index.js';
import type { StorageVerdict } from '../../../src/offline/storage/guard.js';

/** 1600px on the long edge, quality 0.7. From file 22's battery and resilience section. */
const MAX_EDGE = 1600;
const QUALITY = 0.7;

export default function PhotoScreen() {
  const { t } = useLocale();
  const { media } = useOffline();
  const router = useRouter();
  const [permission, requestPermission] = useCameraPermissions();
  const [verdict, setVerdict] = useState<StorageVerdict | null>(null);
  const camera = useRef<CameraView>(null);

  useEffect(() => {
    if (!media) return;
    void storageVerdict(media).then(setVerdict);
  }, [media]);

  if (verdict === null) return <Screen />;

  if (!verdict.mayCapture) {
    return (
      <Screen>
        <Heading>{t('permission.camera.title')}</Heading>
        <Card>
          {/* Names the number and does not open the camera. A silent capture failure is
              discovered days later by someone who no longer has access to the house. */}
          <Text>{t(verdict.messageKey!, verdict.values)}</Text>
        </Card>
        <Button label={t('action.cancel')} onPress={() => router.back()} />
      </Screen>
    );
  }

  if (!permission?.granted) {
    return (
      <Screen>
        <Heading>{t('permission.camera.title')}</Heading>
        <Text>{t('permission.camera.why')}</Text>
        <Button
          label={t('action.understood')}
          onPress={() => {
            void requestPermission();
          }}
        />
        <Button label={t('action.cancel')} variant="secondary" onPress={() => router.back()} />
      </Screen>
    );
  }

  return (
    <View style={styles.fill}>
      <CameraView ref={camera} style={styles.fill} facing="back" />
      {verdict.level === 'low' ? (
        <View style={styles.warning}>
          <Text size="sm" colour="#FFECEC">
            {t(verdict.messageKey!, verdict.values)}
          </Text>
        </View>
      ) : null}
      <Pressable
        testID="shutter"
        accessibilityRole="button"
        accessibilityLabel={t('report.photo')}
        onPress={() => {
          void (async () => {
            const shot = await camera.current?.takePictureAsync({ quality: 1, exif: true });
            if (!shot) return;
            const compressed = await ImageManipulator.manipulateAsync(
              shot.uri,
              [{ resize: { width: MAX_EDGE } }],
              { compress: QUALITY, format: ImageManipulator.SaveFormat.JPEG },
            );
            // The EXIF GPS is deliberately not carried into the compressed file:
            // `manipulateAsync` drops it, and the coordinate the report needs is the one
            // captured separately into a column. A photo that may later be shown to the
            // public should not carry a household's address inside it.
            router.back();
            router.setParams({ photoUri: compressed.uri });
          })();
        }}
        style={[
          styles.shutter,
          { width: touchTarget('sos') * 1.4, height: touchTarget('sos') * 1.4 },
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  warning: {
    position: 'absolute',
    top: SPACE[6],
    left: SPACE[4],
    right: SPACE[4],
    padding: SPACE[3],
    borderRadius: 8,
    backgroundColor: '#7F1D1D',
  },
  shutter: {
    position: 'absolute',
    bottom: SPACE[10],
    alignSelf: 'center',
    borderRadius: 999,
    backgroundColor: '#FFFFFF',
    borderWidth: 4,
    borderColor: ACCENT,
  },
});
