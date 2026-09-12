/**
 * First launch.
 *
 * Language, then the phone number, then the privacy screen, then an optional household
 * link. The order is deliberate: nothing is asked for before the user can read the screen
 * asking, and nothing personal is asked for before they have been told what happens to it.
 */

import { Stack } from 'expo-router';

export default function OnboardingLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
