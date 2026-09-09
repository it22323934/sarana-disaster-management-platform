/**
 * The Field Companion's offline suite.
 * `pnpm --filter mobile test:e2e -- --config field-offline-6h.config.ts`
 *
 * File 24's second Definition-of-Done command. Same runner as `offline.config.ts` and
 * `citizen-offline.config.ts`: it needs `maestro`, `adb` and an attached device, and when
 * they are absent it prints every flow with the failure each would catch and **exits
 * non-zero**. It does not skip and it does not pass. A suite that reports success on a
 * machine with no device turns "the offline path is tested" into a sentence nobody has
 * checked, which is the claim these flows exist to make true.
 *
 * The headline flow is the brief's own worst case: forty assessments and eighty photographs
 * across six hours of airplane mode, the app killed twice, then reconnected. Its
 * deterministic twin is `test/field-offline.test.ts`, which runs on every commit against
 * real SQLite and a fake server. **Both exist, and neither replaces the other.** The unit
 * test proves the sync arithmetic; only a device proves that six hours of camera use, a
 * real Doze cycle and two OS-initiated process kills leave the same forty rows behind.
 *
 * Where a case cannot be driven honestly, it is adjusted and the flow says so — the same
 * discipline files 22 and 23 used. Nothing here is faked to go green.
 */

import type { OfflineE2EConfig } from './offline.config.js';

const ALL_LOCALES = ['si', 'ta', 'en'] as const;

const config: OfflineE2EConfig = {
  appId: 'lk.sarana.app',
  // API 31, matching the other two suites. The target handset is three to four years old,
  // and testing only against the current API hides the Doze behaviour a six-hour session
  // walks straight into.
  device: { platform: 'android', apiLevel: 31 },
  flows: [
    {
      file: 'field-6h-forty-assessments.yaml',
      title:
        'Six hours in airplane mode: 40 assessments, 80 photos, app killed twice, then reconnected',
      proves:
        'A day of fieldwork in a cut-off division reaches the server exactly once, with ' +
        'every photograph attached to the assessment that explains it. A duplicate here is ' +
        'two payments against one household; a loss is a household that receives nothing ' +
        'and an officer who cannot show they surveyed it.',
      locales: ['en'],
    },
    {
      file: 'field-assessment-90s.yaml',
      title: 'One assessment, start to saved, in under 90 seconds offline',
      proves:
        'The recovery pace the brief sets: 30 to 60 assessments a day, on foot, in rain. ' +
        'Past ninety seconds an officer stops filling the form properly and starts ' +
        'guessing, and the guesses are what the Aid Ledger then pays against.',
      locales: ['en'],
    },
    {
      file: 'field-out-of-bounds-refused.yaml',
      title: 'An out-of-range quantity is refused on the device, with the ceiling named',
      proves:
        'The rejection happens while the officer is standing at the house, not three weeks ' +
        'later. By then the debris is cleared and the assessment cannot be redone.',
      locales: ['en'],
    },
    {
      file: 'field-paper-qr-prefill.yaml',
      title: 'A paper form QR pre-fills the digital form and the record carries source PAPER',
      proves:
        'A dead phone in week three of a recovery does not become a permanent gap in the ' +
        'ledger. The audit trail survives the paper stage.',
      locales: ['en'],
    },
    {
      file: 'field-conflict-explicit-choice.yaml',
      title: 'A conflict is shown local-beside-server and cannot be dismissed without a choice',
      proves:
        'The platform never resolves a disagreement about what happened in a division on ' +
        "the officer's behalf. Auto-merging would decide it in favour of whoever wrote the " +
        'merge rule, silently, in a record that becomes money.',
      locales: ['en'],
    },
    {
      file: 'field-queue-export-import.yaml',
      title: 'A failing handset exports its queue and a replacement imports and syncs it',
      proves:
        'Three weeks of work survives a dying battery. Without this the only route off a ' +
        'failing device is a re-survey nobody funds.',
      locales: ['en'],
    },
    {
      file: 'field-register-search-offline.yaml',
      title: 'The household register searches with no signal, and says what it cannot match',
      proves:
        'Step one of the form is "select household". If it needed a network the app would ' +
        'be unusable in exactly the divisions that most need assessing. The search matches ' +
        'whole name tokens only, and the screen says so rather than showing an empty list ' +
        'that reads as "no such household".',
      locales: ['en'],
    },
    {
      file: 'field-pin-on-open.yaml',
      title: 'The app asks for a PIN on open and after the idle timeout',
      proves:
        "This runs on an officer's personal phone. A lost handset must not hand its finder " +
        'the division register.',
      locales: ['en'],
    },
    {
      file: 'field-dynamic-type-200.yaml',
      title: 'Every field screen at 200% text in three languages, no overflow',
      proves:
        'A GN officer reading a form in bright sun with the system font scaled up is the ' +
        'normal case, not an accessibility edge case. A Tamil label that breaks a slot ' +
        'sized in English is the failure that actually happens.',
      locales: ALL_LOCALES,
      fontScale: 2,
    },
  ],
};

export default config;
