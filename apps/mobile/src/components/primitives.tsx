/**
 * The handful of primitives every screen is built from.
 *
 * Small on purpose. `@sarana/ui` is a DOM component library and cannot render here, so
 * the design system reaches this app as tokens rather than components - and a second
 * component library would be a second place for the two to drift apart. What is here is
 * the minimum that enforces the three rules the brief is explicit about: three scripts,
 * dynamic type to 200%, and a 44x44 touch floor.
 */

import type { ReactNode } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text as RNText,
  View,
  useColorScheme,
} from 'react-native';
import type { StyleProp, TextStyle, ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useLocale } from '../providers/LocaleProvider.js';
import { RADIUS, SPACE, SURFACES, touchTarget, type, type TypeSize } from '../theme/index.js';

export function useSurface() {
  return SURFACES[useColorScheme() === 'dark' ? 'dark' : 'light'];
}

export interface TextProps {
  readonly children: ReactNode;
  readonly size?: TypeSize;
  readonly weight?: 'regular' | 'medium' | 'semibold';
  readonly muted?: boolean;
  readonly colour?: string;
  readonly align?: 'left' | 'center' | 'right';
  readonly style?: StyleProp<TextStyle>;
  readonly numberOfLines?: number;
  readonly accessibilityRole?: 'header' | 'text' | 'summary';
}

/**
 * Text, with the script metrics already applied.
 *
 * Every string in the app goes through here. A bare `<Text>` would render Sinhala at
 * Latin leading, where the ේ of one line touches the ු of the line above - which is the
 * exact failure the design system's three-script type scale exists to prevent.
 */
export function Text({
  children,
  size = 'base',
  weight = 'regular',
  muted = false,
  colour,
  align,
  style,
  numberOfLines,
  accessibilityRole,
}: TextProps) {
  const { locale } = useLocale();
  const surface = useSurface();
  const metrics = type(size, locale);

  return (
    <RNText
      accessibilityRole={accessibilityRole}
      numberOfLines={numberOfLines}
      // The OS scale is already folded into `metrics`, and applied twice it doubles.
      allowFontScaling={false}
      style={[
        metrics,
        {
          color: colour ?? (muted ? surface.muted : surface.text),
          fontWeight: weight === 'regular' ? '400' : weight === 'medium' ? '500' : '600',
          textAlign: align,
        },
        style,
      ]}
    >
      {children}
    </RNText>
  );
}

export function Heading({ children, size = 'xl' }: { children: ReactNode; size?: TypeSize }) {
  return (
    <Text size={size} weight="semibold" accessibilityRole="header">
      {children}
    </Text>
  );
}

export interface ScreenProps {
  /**
   * Optional, because a screen waiting on its first local read renders an empty frame.
   *
   * Not a spinner: reading a row out of SQLite takes milliseconds, and a spinner that
   * flashes for one frame is worse than a background colour that does not.
   */
  readonly children?: ReactNode;
  /** Scrolling is the default: a form at 200% text size is taller than any handset. */
  readonly scroll?: boolean;
  readonly style?: StyleProp<ViewStyle>;
}

export function Screen({ children, scroll = true, style }: ScreenProps) {
  const surface = useSurface();
  const content = (
    <View style={[styles.screen, { backgroundColor: surface.base }, style]}>{children}</View>
  );

  return (
    <SafeAreaView edges={['top', 'left', 'right']} style={{ flex: 1, backgroundColor: surface.base }}>
      {scroll ? (
        <ScrollView
          contentContainerStyle={{ flexGrow: 1 }}
          keyboardShouldPersistTaps="handled"
          // The strip is pinned outside the scroll view, so it stays visible while the
          // officer works down a long form.
        >
          {content}
        </ScrollView>
      ) : (
        content
      )}
    </SafeAreaView>
  );
}

export interface ButtonProps {
  readonly label: string;
  readonly onPress: () => void;
  readonly variant?: 'primary' | 'secondary' | 'danger';
  readonly disabled?: boolean;
  readonly size?: 'default' | 'sos';
  readonly accessibilityHint?: string;
}

/**
 * A button that cannot be smaller than the touch floor.
 *
 * 44x44 minimum, 56x56 for the SOS control, and both grow with the OS text size: a
 * control sized for 16px text has to fit 32px text too, or the label is clipped at
 * exactly the setting that exists to make it readable.
 */
export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled = false,
  size = 'default',
  accessibilityHint,
}: ButtonProps) {
  const surface = useSurface();
  const minHeight = touchTarget(size === 'sos' ? 'sos' : 'min');

  const background =
    variant === 'primary' ? '#0E7C86' : variant === 'danger' ? '#DC2626' : 'transparent';
  const foreground = variant === 'secondary' ? surface.text : '#FFFFFF';

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled }}
      style={({ pressed }) => [
        styles.button,
        {
          minHeight,
          minWidth: minHeight,
          backgroundColor: background,
          borderColor: variant === 'secondary' ? surface.divider : background,
          opacity: disabled ? 0.5 : pressed ? 0.85 : 1,
        },
      ]}
    >
      <Text
        weight="medium"
        colour={foreground}
        align="center"
        size={size === 'sos' ? 'lg' : 'base'}
      >
        {label}
      </Text>
    </Pressable>
  );
}

/** A bordered block for something that needs to be read as one thing. */
export function Card({ children }: { children: ReactNode }) {
  const surface = useSurface();
  return (
    <View
      style={[styles.card, { backgroundColor: surface.card, borderColor: surface.divider }]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, gap: SPACE[4], padding: SPACE[4] },
  button: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: SPACE[4],
    paddingVertical: SPACE[2],
    borderRadius: RADIUS.default,
    borderWidth: 1,
  },
  card: {
    gap: SPACE[2],
    padding: SPACE[4],
    borderRadius: RADIUS.surface,
    borderWidth: 1,
  },
});
