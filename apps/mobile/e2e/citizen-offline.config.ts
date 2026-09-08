/**
 * The citizen offline suite.
 *
 * Same runner as `offline.config.ts`, different flows: these are the cases file 23 names,
 * and the one that has a number attached is the report flow. **Under thirty seconds from
 * tapping SOS to a submitted report, entirely offline** - measured by the runner from the
 * Maestro trace, not eyeballed.
 *
 * The budget is a hard assertion rather than a note, because thirty seconds is not a
 * performance target. It is roughly how long a person will keep tapping at a phone while
 * water is coming in, and past it they put the phone down.
 */

import type { OfflineE2EConfig } from './offline.config.js';

const ALL_LOCALES = ['si', 'ta', 'en'] as const;

const config: OfflineE2EConfig = {
  appId: 'lk.sarana.app',
  device: { platform: 'android', apiLevel: 31 },
  flows: [
    {
      file: 'citizen-sos-30s.yaml',
      title: 'Airplane mode, cold start: SOS to submitted report in under 30 seconds',
      proves:
        'The emergency path is usable by someone who is panicking. Past thirty seconds ' +
        'they put the phone down, and the report that would have been filed is not.',
      locales: ['en'],
    },
    {
      file: 'citizen-report-minimal.yaml',
      title: 'A report with no location and no media submits successfully',
      proves:
        'GPS indoors during a storm is often nothing. Blocking on it would refuse exactly ' +
        'the reports that most need to be accepted.',
      locales: ['en'],
    },
    {
      file: 'citizen-people-unknown.yaml',
      title: '"I don\'t know" for people-at-risk sends null, never zero',
      proves:
        'A dispatcher can ask about an unknown. A fabricated zero cannot be told from a ' +
        'counted one, and it is the number that decides who gets a boat first.',
      locales: ['en'],
    },
    {
      file: 'citizen-severity-3-delivers.yaml',
      title: 'A severity 3 alert arrives with notifications muted',
      proves: 'An evacuation order is not a notification preference.',
      locales: ['en'],
    },
    {
      file: 'citizen-grievance-offline.yaml',
      title: 'The grievance flow completes offline and syncs',
      proves:
        'A household in a cut-off division has the same right to raise a grievance as one ' +
        'in Colombo. If it needed a network, it would not.',
      locales: ['en'],
    },
    {
      file: 'citizen-entitlement-explained.yaml',
      title: 'The entitlement working renders in si, ta and en',
      proves:
        'The transparency promise reaches the household in their own language, or it does ' +
        'not reach them.',
      locales: ALL_LOCALES,
    },
    {
      file: 'citizen-dynamic-type-200.yaml',
      title: 'Every citizen screen at 200% text in three languages, no overflow',
      proves:
        'The accessibility setting that exists to make text readable does not clip it. ' +
        'The SOS button and the six incident tiles are what break first.',
      locales: ALL_LOCALES,
      fontScale: 2,
    },
  ],
};

export default config;
