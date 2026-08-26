import { StyleSheet, Text, View } from 'react-native';

/**
 * The app shell.
 *
 * The citizen report flow, the alert inbox and the Field Companion assessment forms are
 * built in a later step. This screen exists so the app boots and states what it is.
 */
export default function Index() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>SARANA</Text>
      <Text style={styles.subtitle}>සරණ · சரண</Text>
      <Text style={styles.body}>
        Report a problem, receive warnings, and track aid - in Sinhala, Tamil or English.
        Works without a connection: what you record is saved on the device and syncs when
        the network returns.
      </Text>
      <Text style={styles.note}>Simulated data. No live government system is connected.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    padding: 32,
  },
  title: { fontSize: 34, fontWeight: '600', letterSpacing: 2 },
  // Sinhala and Tamil glyphs need more vertical room than Latin at the same size.
  subtitle: { fontSize: 20, lineHeight: 34, opacity: 0.8 },
  body: { fontSize: 15, lineHeight: 24, textAlign: 'center' },
  note: { fontSize: 12, opacity: 0.6, textAlign: 'center', marginTop: 8 },
});
