/**
 * One text input, with the three rules applied.
 *
 * Written once because it was being written four times: the script metrics, the 44pt
 * floor that grows with the text setting, and `allowFontScaling={false}` - which looks
 * backwards and is not. The OS scale is already folded into `type()`, and letting React
 * Native apply it again doubles it, so a user at 200% gets 400%.
 */

import { TextInput, type KeyboardTypeOptions } from 'react-native';
import { View } from 'react-native';

import { Text, useSurface } from './primitives.js';
import { useLocale } from '../providers/LocaleProvider.js';
import { RADIUS, SPACE, touchTarget, type } from '../theme/index.js';

export interface TextFieldProps {
  readonly label: string;
  readonly value: string;
  readonly onChange: (next: string) => void;
  readonly keyboardType?: KeyboardTypeOptions;
  readonly secure?: boolean;
  readonly multiline?: boolean;
  readonly autoCapitalize?: 'none' | 'characters' | 'words' | 'sentences';
  /** Shown under the field. Never a placeholder: a placeholder vanishes as you type. */
  readonly hint?: string;
}

export function TextField({
  label,
  value,
  onChange,
  keyboardType,
  secure = false,
  multiline = false,
  autoCapitalize = 'none',
  hint,
}: TextFieldProps) {
  const { locale } = useLocale();
  const surface = useSurface();
  const metrics = type('base', locale);

  return (
    <View style={{ gap: SPACE[1] }}>
      <Text size="sm" muted>
        {label}
      </Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        keyboardType={keyboardType}
        secureTextEntry={secure}
        multiline={multiline}
        autoCapitalize={autoCapitalize}
        accessibilityLabel={label}
        allowFontScaling={false}
        placeholderTextColor={surface.muted}
        style={{
          ...metrics,
          color: surface.text,
          backgroundColor: surface.raised,
          borderColor: surface.divider,
          borderWidth: 1,
          borderRadius: RADIUS.default,
          paddingHorizontal: SPACE[3],
          paddingVertical: multiline ? SPACE[2] : 0,
          minHeight: multiline ? touchTarget('min') * 2 : touchTarget('min'),
          textAlignVertical: multiline ? 'top' : 'center',
        }}
      />
      {hint ? (
        <Text size="xs" muted>
          {hint}
        </Text>
      ) : null}
    </View>
  );
}
