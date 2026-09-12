/**
 * The six incident types, as buttons big enough to hit with a wet thumb.
 *
 * Icon **and** label, never icon alone. An icon-only grid asks a frightened person to
 * decode a pictogram; a label-only grid asks someone with low literacy to read six
 * phrases. Both together is the only version that works for everyone the app has to work
 * for, and it is why the tiles are large rather than the icons small.
 *
 * The icons are drawn rather than loaded from a font. A font icon at 200% dynamic type
 * either scales with the text and blurs, or does not scale and becomes a decoration next
 * to a headline - and the whole point of the tile is that the two are read together.
 */

import { Pressable, StyleSheet, View, useColorScheme } from 'react-native';
import Svg, { Circle, Path, Rect } from 'react-native-svg';

import { INCIDENT_TYPES, type IncidentType } from '../report-draft.js';
import { Text, useSurface } from '../../components/primitives.js';
import { useLocale } from '../../providers/LocaleProvider.js';
import { ACCENT, ACCENT_DEEP, RADIUS, SPACE, fontScale, touchTarget } from '../../theme/index.js';

/**
 * One shape per type.
 *
 * A `switch` with an exhaustiveness check rather than a lookup: a type added to
 * `INCIDENT_TYPES` without a shape here fails the build, instead of rendering an empty
 * tile with a label under it.
 */
function shapeFor(type: IncidentType, colour: string) {
  const stroke = { stroke: colour, strokeWidth: 2, fill: 'none' as const };
  switch (type) {
    case 'FLOOD':
      return (
        <>
          <Path d="M2 16c3-3 5-3 8 0s5 3 8 0" {...stroke} />
          <Path d="M2 11c3-3 5-3 8 0s5 3 8 0" {...stroke} />
          <Path d="M2 21c3-3 5-3 8 0s5 3 8 0" {...stroke} />
        </>
      );
    case 'TRAPPED':
      // A person inside a closed box. Deliberately not a running figure: the difference
      // between "trapped" and "evacuating" is the whole point of the category.
      return (
        <>
          <Rect x="3" y="3" width="18" height="18" rx="2" {...stroke} />
          <Circle cx="12" cy="9" r="2" {...stroke} />
          <Path d="M8 18c0-3 2-4 4-4s4 1 4 4" {...stroke} />
        </>
      );
    case 'MEDICAL':
      return <Path d="M12 4v16M4 12h16" {...stroke} />;
    case 'STRUCTURAL':
      // A house with a crack through it.
      return (
        <>
          <Path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" {...stroke} />
          <Path d="M10 21l2-6-2-2 3-3" {...stroke} />
        </>
      );
    case 'LANDSLIDE':
      return (
        <>
          <Path d="M2 20h20" {...stroke} />
          <Path d="M3 20L11 6l6 9 3 5" {...stroke} />
          <Circle cx="15" cy="19" r="1.5" {...stroke} />
          <Circle cx="9" cy="18" r="1" {...stroke} />
        </>
      );
    case 'OTHER':
      return (
        <>
          <Circle cx="12" cy="12" r="9" {...stroke} />
          <Path d="M9.5 9.5a2.5 2.5 0 1 1 3 2.5v1.5" {...stroke} />
          <Circle cx="12" cy="17" r="0.6" fill={colour} stroke="none" />
        </>
      );
  }
}

function Glyph({ type, size, colour }: { type: IncidentType; size: number; colour: string }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {shapeFor(type, colour)}
    </Svg>
  );
}

export interface IncidentTypeGridProps {
  readonly selected: IncidentType | null;
  readonly onSelect: (type: IncidentType) => void;
}

export function IncidentTypeGrid({ selected, onSelect }: IncidentTypeGridProps) {
  const { t } = useLocale();
  const surface = useSurface();
  const scheme = useColorScheme() === 'dark' ? 'dark' : 'light';
  // The tile grows with the text: at 200% the label needs two lines and the icon has to
  // stay proportionate to it, or the tile turns into a caption under a picture.
  const tile = Math.max(touchTarget('min') * 2, 96 * fontScale());

  return (
    <View style={styles.grid} accessibilityRole="radiogroup">
      {INCIDENT_TYPES.map((type) => {
        const active = selected === type;
        const foreground = active ? '#FFFFFF' : surface.text;
        return (
          <Pressable
            key={type}
            onPress={() => onSelect(type)}
            accessibilityRole="radio"
            accessibilityState={{ selected: active }}
            accessibilityLabel={t(`report.type.${type}`)}
            style={[
              styles.tile,
              {
                minHeight: tile,
                backgroundColor: active ? (scheme === 'dark' ? ACCENT_DEEP : ACCENT) : surface.card,
                borderColor: active ? ACCENT : surface.divider,
              },
            ]}
          >
            <Glyph type={type} size={Math.round(28 * fontScale())} colour={foreground} />
            <Text size="sm" weight="medium" align="center" colour={foreground}>
              {t(`report.type.${type}`)}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE[2] },
  tile: {
    // Two per row at any text size. Three would put a Sinhala label on four lines.
    flexBasis: '47%',
    flexGrow: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: SPACE[2],
    padding: SPACE[3],
    borderRadius: RADIUS.surface,
    borderWidth: 1,
  },
});
