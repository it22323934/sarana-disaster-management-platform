/**
 * The offline end-to-end suite.
 *
 * Maestro rather than Detox: the cases that matter here are about the *device*, not the
 * component tree - airplane mode, a process kill, a full disk - and Detox drives a
 * JavaScript bridge that has to be alive to answer. Maestro drives the OS, so it can
 * still assert on the screen after the app has been force-stopped.
 *
 * Every flow below is one of the cases file 22 names under "test cases that must exist".
 * Each states, in `proves`, the failure it would catch - a flow whose failure mode nobody
 * can name is a flow that gets deleted the first time it goes red.
 */

export interface Flow {
  readonly file: string;
  readonly title: string;
  /** What goes wrong in the field if this flow fails. */
  readonly proves: string;
  /** Locales this flow runs in. Layout flows run in all three; logic flows run in one. */
  readonly locales: readonly ('si' | 'ta' | 'en')[];
  /** Text scale, as a multiplier of the system default. */
  readonly fontScale?: number;
}

export interface OfflineE2EConfig {
  readonly appId: string;
  /** The device the app is designed for: mid-range Android, 3-4 years old, 3GB RAM. */
  readonly device: { readonly platform: 'android'; readonly apiLevel: number };
  readonly flows: readonly Flow[];
}

const ALL_LOCALES = ['si', 'ta', 'en'] as const;

const config: OfflineE2EConfig = {
  appId: 'lk.sarana.app',
  // API 31 rather than the newest: the target handset is three to four years old, and
  // testing only against the current API hides the Doze and background-task behaviour
  // that the fifteen-minute sync actually runs into.
  device: { platform: 'android', apiLevel: 31 },
  flows: [
    {
      file: 'airplane-twenty-assessments.yaml',
      title: 'Airplane mode: 20 assessments with photos, killed, reopened, reconnected',
      proves:
        'A day of fieldwork in a cut-off division reaches the server exactly once. A ' +
        'duplicate here is two payments against one household; a loss is none.',
      locales: ['en'],
    },
    {
      file: 'interrupted-mid-batch.yaml',
      title: 'Sync interrupted mid-batch and resumed',
      proves:
        'The device does not create a second copy of an operation whose response was ' +
        'lost. This is what client_operation_id exists for.',
      locales: ['en'],
    },
    {
      file: 'operation-log-gap.yaml',
      title: 'Operation log gap pauses the device and names the missing seq',
      proves:
        'A hole in the log stops the sync rather than rebuilding a household record out ' +
        'of an update whose create never arrived.',
      locales: ['en'],
    },
    {
      file: 'logout-refused.yaml',
      title: 'Sign-out is refused while unsynced operations exist',
      proves:
        'An officer cannot end a shift by deleting it. The refusal names the count and ' +
        'offers sync or export, never a plain dismiss.',
      locales: ['en'],
    },
    {
      file: 'storage-full.yaml',
      title: 'Photo capture is refused with a message when storage is full',
      proves:
        'A full device says so before the camera opens, instead of returning a ' +
        'zero-byte file that is discovered three days later by a reviewer.',
      locales: ['en'],
    },
    {
      file: 'status-strip-states.yaml',
      title: 'The status strip reads correctly in all four states',
      proves:
        'The one question a field officer must be able to answer at a glance - is my ' +
        'work safe - has a correct answer on screen in every state.',
      locales: ALL_LOCALES,
    },
    {
      file: 'dynamic-type-200.yaml',
      title: 'Every screen renders at 200% text in si, ta and en without overflow',
      proves:
        'The accessibility setting that exists to make text readable does not clip the ' +
        'text. Sinhala and Tamil are the ones that break first.',
      locales: ALL_LOCALES,
      fontScale: 2,
    },
  ],
};

export default config;
