/**
 * Getting a position, and giving up quickly when there is not one.
 *
 * The rule the report flow depends on: **never block submission on location.** GPS
 * indoors during a storm is often nothing at all, and the reports that most need to be
 * accepted are exactly the ones filed from inside a building with water coming in.
 *
 * So this has a deadline. Eight seconds, then whatever it has - which may be nothing, and
 * nothing is a valid answer that the flow already handles.
 */

import * as Location from 'expo-location';

import type { ReportLocation } from './report-draft.js';

/**
 * How long to wait for a fix.
 *
 * Eight seconds is roughly a cold GPS lock outdoors with a clear sky, and roughly forever
 * indoors. Past it the marginal chance of a fix is not worth the seconds against a
 * thirty-second budget.
 */
export const LOCATION_DEADLINE_MS = 8_000;

/**
 * Accuracy, and why it is not `High`.
 *
 * `Balanced` uses the network and the cell towers as well as GPS, gets a usable fix
 * indoors where `High` gets none, and costs a fraction of the battery - which matters when
 * the device is on 2% and the person still has a night ahead of them. `High` is reserved
 * for an active SOS where a responder is already moving toward the coordinate.
 */
const DEFAULT_ACCURACY = Location.Accuracy.Balanced;

export interface CaptureOptions {
  readonly accuracy?: Location.LocationAccuracy;
  readonly deadlineMs?: number;
}

/**
 * One position, or null.
 *
 * Null covers all three ways this fails - permission refused, location services off, no
 * fix before the deadline - because the flow does the same thing in all three: it asks for
 * a landmark instead and accepts the report either way. Distinguishing them would be
 * three messages for one action.
 */
export async function captureLocation(options: CaptureOptions = {}): Promise<ReportLocation | null> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== Location.PermissionStatus.GRANTED) return null;

  const deadline = new Promise<null>((resolve) =>
    setTimeout(() => resolve(null), options.deadlineMs ?? LOCATION_DEADLINE_MS),
  );

  const fix = Location.getCurrentPositionAsync({
    accuracy: options.accuracy ?? DEFAULT_ACCURACY,
  })
    .then(
      (position): ReportLocation => ({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracyMetres: position.coords.accuracy,
        // `gps` is what the device thinks it did. A Balanced fix may in fact have come
        // from a cell tower, and incident-svc's `location_source` vocabulary has a word
        // for that - but the platform does not tell us which it used, and guessing would
        // put a wrong provenance on a coordinate an anomaly detector later reads.
        source: 'gps',
      }),
    )
    .catch(() => null);

  return Promise.race([fix, deadline]);
}

/**
 * A high-accuracy position, for an SOS that has already been dispatched.
 *
 * Called only while a responder is moving toward the coordinate - which is the one
 * situation where the battery cost is worth paying, and the one the brief allows a
 * foreground service for.
 */
export async function captureHighAccuracy(): Promise<ReportLocation | null> {
  return captureLocation({ accuracy: Location.Accuracy.High, deadlineMs: 20_000 });
}
