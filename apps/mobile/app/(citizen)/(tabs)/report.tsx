/**
 * The Report tab.
 *
 * A tab rather than only a button on Home, because someone who has been in the app for a
 * minute reading a warning should not have to navigate back to report. It goes straight
 * to the flow: there is nothing to put on an intermediate screen that is worth a tap.
 */

import { Redirect } from 'expo-router';

export default function ReportTab() {
  return <Redirect href="/(citizen)/report/new" />;
}
