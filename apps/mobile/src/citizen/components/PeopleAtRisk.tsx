/**
 * "Anyone in danger?"
 *
 * The only control in the app with a rule written into its shape: **"I don't know" is as
 * prominent as any number.** It is not a small link under the stepper and it is not the
 * default that gets skipped past - it is a full-width option, styled like the answers, and
 * the hint under it says it is a real answer.
 *
 * The reason is what a dispatcher does with the field. An unknown they know is unknown can
 * be asked about on the way; a fabricated 3 cannot be told apart from a counted 3, and it
 * is the number that decides who gets a boat first.
 */

import { Pressable, StyleSheet, View } from 'react-native';

import { Text, useSurface } from '../../components/primitives.js';
import { useLocale } from '../../providers/LocaleProvider.js';
import { RADIUS, SPACE, touchTarget } from '../../theme/index.js';

/** How high the quick buttons go before the stepper takes over. */
const QUICK = [0, 1, 2, 3, 4, 5] as const;

export interface PeopleAtRiskProps {
  /** `null` means the person said they do not know. Never conflated with zero. */
  readonly value: number | null;
  readonly onChange: (value: number | null) => void;
}

export function PeopleAtRisk({ value, onChange }: PeopleAtRiskProps) {
  const { t } = useLocale();
  const surface = useSurface();
  const size = touchTarget('min');

  return (
    <View style={{ gap: SPACE[2] }}>
      <Text size="sm" weight="medium">
        {t('report.peopleTitle')}
      </Text>

      <View style={styles.row}>
        {QUICK.map((count) => {
          const active = value === count;
          return (
            <Pressable
              key={count}
              onPress={() => onChange(count)}
              accessibilityRole="radio"
              accessibilityState={{ selected: active }}
              accessibilityLabel={t('report.peopleCount', { count })}
              style={[
                styles.quick,
                {
                  minWidth: size,
                  minHeight: size,
                  backgroundColor: active ? '#0E7C86' : surface.card,
                  borderColor: active ? '#0E7C86' : surface.divider,
                },
              ]}
            >
              <Text weight="medium" colour={active ? '#FFFFFF' : surface.text}>
                {count === 5 ? '5+' : String(count)}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <Pressable
        onPress={() => onChange(null)}
        accessibilityRole="radio"
        accessibilityState={{ selected: value === null }}
        accessibilityLabel={t('report.peopleDontKnow')}
        accessibilityHint={t('report.peopleDontKnowHint')}
        style={[
          styles.unknown,
          {
            minHeight: size,
            // Same weight as a number, never a quieter escape hatch. Making it look like
            // a refusal to answer is how a guess gets entered instead.
            backgroundColor: value === null ? '#0E7C86' : surface.card,
            borderColor: value === null ? '#0E7C86' : surface.divider,
          },
        ]}
      >
        <Text weight="medium" colour={value === null ? '#FFFFFF' : surface.text}>
          {t('report.peopleDontKnow')}
        </Text>
      </Pressable>

      <Text size="xs" muted>
        {t('report.peopleDontKnowHint')}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE[2] },
  quick: {
    flexGrow: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: SPACE[3],
    borderRadius: RADIUS.default,
    borderWidth: 1,
  },
  unknown: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: SPACE[4],
    paddingVertical: SPACE[2],
    borderRadius: RADIUS.default,
    borderWidth: 1,
  },
});
