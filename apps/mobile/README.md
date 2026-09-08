# SARANA mobile

One Expo application, two role-gated surfaces: the **Citizen app** and the **Field
Companion** for GN officers. Which one a user sees is decided by their role at sign-in,
not by installing a different app — a GN officer is also a citizen, and during a flood
they are a citizen first.

Designed for the actual device: a mid-range Android, three to four years old, 3GB RAM, on
a congested or absent network, held by someone who is wet, frightened, or working a
fourteen-hour shift.

## Commands

```bash
pnpm --filter mobile dev            # expo start
pnpm --filter mobile typecheck
pnpm --filter mobile test           # 143 tests, no device needed
pnpm --filter mobile verify-i18n    # three locales, and every key the code asks for
pnpm --filter mobile test:e2e -- --config offline.config.ts   # Maestro; needs a device
eas build --profile preview --platform android --local
```

## Where things are

```
app/                 expo-router routes. (citizen) and (field) are the two surfaces.
src/offline/         the offline core. Nothing in here imports React.
  db/                the Database port, the schema, the expo-sqlite adapter
  log/               the append-only operation log and its ordering rules
  sync/              the engine, backoff, connectivity, the transport port
  media/             the second, resumable queue that runs behind the log
  storage/           the disk thresholds
  status/            what the status strip says, as a pure function
src/auth/            token storage, the offline capability token, the logout refusal
src/i18n/            si/ta/en, chosen before login
src/theme/           @sarana/ui tokens, in React Native units
test-support/        a real SQLite engine and a fake server that follows the real contract
e2e/                 Maestro flows for the cases that need a device
```

## The offline architecture

```
UI  →  local SQLite (source of truth on device)  →  operation log  →  sync engine  →  API
                    ▲                                                        │
                    └──────────── server reconciliation ─────────────────────┘
```

Every write lands in SQLite first and the UI reflects it immediately. Sync is a background
reconciliation, never a blocking step. A GN officer who taps Save and waits for a spinner
during a flood has been failed by the design.

Conflicts are surfaced, never merged (ADR-006). The log is never truncated until the
server confirms.

## Decisions worth not re-litigating

**`expo-audio`, not `expo-av`.** The brief names `expo-av`; its last release is 16.0.8,
for SDK 53/54, and it is not published on the SDK 57 line this app is pinned to.
`expo-audio` is its successor and has the same recording surface.

**The tests run against real SQLite, not a fake.** `test-support/node-database.ts` is
Node's built-in `node:sqlite` behind the same `Database` port `expo-sqlite` implements, so
the migrations, the CHECK constraints and the SQL in the tests are the ones that ship. What
a test cannot see is SQLCipher and the JSI bridge; everything above them is identical.

**`ACCESS_BACKGROUND_LOCATION` is in `blockedPermissions`, deliberately.** No continuous
background location, ever. A foreground service during an active incident, with a visible
notification, and nothing else: silent background tracking of citizens during a disaster is
both a battery problem and a trust problem.

**The status strip is the most important component in the app**, and everything it says is
a pure function in `src/offline/status/model.ts`. The rendering is thirty lines; the
decision about what a device in a given state should tell an officer is tested twelve ways.

**The debug bridge exists and is guarded twice.** `sarana://debug?action=...` manufactures
states no amount of tapping can reach — a hole in the operation log, a full disk, a
conflict the server has already recorded. `runDebugAction` refuses on anything that is not
a development build, before it looks at the action.

## What is not built here

The citizen report flow, the alert inbox and the grievance tracker are file 23. The
assessment form, the household list and the offline map are file 24. `app/(citizen)` and
`app/(field)` hold shells so the core underneath them can be exercised on a device.

Sign-in seats a session without calling core-api. The endpoints exist
(`/auth/login`, `/auth/otp/verify`, `/auth/capability-token`); wiring them is part of the
two surfaces, and the screen says so in a comment rather than pretending.
