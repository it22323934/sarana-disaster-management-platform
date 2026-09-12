/**
 * The offline status strip.
 *
 * Persistent, non-dismissible, on every screen. It answers one question - **is my work
 * safe?** - and a GN officer has to be able to answer it in under a second, at a glance,
 * in rain, without tapping anything.
 *
 * What the design rules out is as important as what it does:
 *
 *   - **No spinner without a number.** A spinner says "wait"; it does not say for how
 *     long or for how many, and the officer's actual decision is whether to keep walking.
 *   - **Colour is never the only signal.** A glyph carries the same information, because
 *     the strip is read at a glance by someone who may be colour-blind and is definitely
 *     not looking closely.
 *   - **It cannot be dismissed.** The one state a user would want to dismiss - "2 items
 *     need attention" - is the one they must not be able to.
 *
 * Everything it says comes from `statusStrip` in `offline/status/model.ts`, which is
 * pure and tested. This file renders.
 */

import { useRouter } from 'expo-router';
import { AccessibilityInfo, Pressable, StyleSheet, Text, useColorScheme } from 'react-native';
import { useEffect, useRef } from 'react';

import { useOffline } from '../providers/OfflineProvider.js';
import { useLocale } from '../providers/LocaleProvider.js';
import { RADIUS, SPACE, statusColours, touchTarget, type } from '../theme/index.js';

export function SyncStatusStrip() {
  const { strip, syncNow } = useOffline();
  const { locale, t } = useLocale();
  const scheme = useColorScheme() === 'dark' ? 'dark' : 'light';
  const router = useRouter();
  const lastAnnounced = useRef<string | null>(null);

  const message = t(strip.messageKey, strip.values);
  const colours = statusColours(strip.tone, scheme);

  useEffect(() => {
    // Announced only on the transitions that change the answer to "is my work safe":
    // everything reaching the server, and anything needing a decision. A screen reader
    // narrating the counter would talk over the officer for the length of a sync.
    if (!strip.announce || lastAnnounced.current === message) return;
    lastAnnounced.current = message;
    AccessibilityInfo.announceForAccessibility(message);
  }, [message, strip.announce]);

  const body = type('sm', locale);

  return (
    <Pressable
      onPress={() => {
        if (strip.attention > 0 || strip.queued > 0) router.push('/sync');
        else void syncNow();
      }}
      accessibilityRole="button"
      accessibilityLabel={t('a11y.syncStrip', { message })}
      accessibilityHint={t('a11y.openSyncDetail')}
      style={[
        styles.strip,
        {
          backgroundColor: colours.background,
          minHeight: touchTarget('min'),
        },
      ]}
    >
      <Text
        style={[styles.glyph, { color: colours.foreground, fontSize: body.fontSize + 2 }]}
        // The glyph duplicates the message for sighted users; reading it aloud as a
        // character name ("black circle") would be noise.
        accessibilityElementsHidden
        importantForAccessibility="no"
      >
        {strip.glyph}
      </Text>
      <Text
        style={[styles.message, body, { color: colours.foreground }]}
        // Three lines at 200% text size. The strip grows rather than truncating: a
        // truncated sync message is a message that does not answer the question.
        numberOfLines={3}
      >
        {message}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  strip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACE[2],
    paddingHorizontal: SPACE[4],
    paddingVertical: SPACE[2],
    borderRadius: RADIUS.cell,
  },
  glyph: {
    // Fixed width so the message starts at the same x in all four states; a message that
    // shifts sideways as the state changes is harder to read at a glance.
    width: 18,
    textAlign: 'center',
  },
  message: { flex: 1 },
});
