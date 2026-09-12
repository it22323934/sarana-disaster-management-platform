# @sarana/ui

The SARANA design system. One system across the operations console, the public dashboard
and both mobile surfaces — it has to work at 3am in an operations room, in the rain on a
mid-range Android, and in a newsroom on a laptop, in three scripts, at equal quality.

```bash
pnpm --filter @sarana/ui storybook     # http://localhost:6006
```

## The two rules

**Colour means severity. Nothing else.** The warm end of the spectrum is reserved entirely
for hazard severity and is never used for chrome, branding, buttons, links, charts or
decoration. Every interface accent is cool, so a coloured element can never be mistaken for
a severity signal. An operator who sees an orange element on this platform is looking at a
watch-level hazard, every time, without having to check. A test in `tokens.test.ts` fails if
a warm value is added to the interface palette.

**Trilingual or it does not ship.** `LocalisedText` takes a `LocalisedText` object and
cannot render a bare string; there is no `string | LocalisedText` overload and there will
not be one. On 28 Nov 2025 the DMC press conference for Cyclone Ditwah went out in Sinhala
and English only, and Tamil-speaking communities were left without the warning. This
package's job is to make that structurally impossible rather than merely discouraged.

## Layout

```
src/tokens/       the single source of truth. tokens.css and tokens.nativewind.js
                  at the package root are GENERATED from it and committed.
src/primitives/   Radix behaviour, SARANA styling. Knows nothing about disasters.
src/data/         DataTable (virtualised), StatCard, TrendSparkline, EmptyState, Pagination
src/domain/       the components that encode a platform rule: SeverityPill, TimeSpine,
                  PendingGateBanner, GNDivisionPicker, MockDataBadge, ConfidenceMeter, ...
src/map/          MapLibre shell (optional peer, loaded on mount) + layer builders
src/forms/        react-hook-form + zod bindings, TrilingualField, OfflineSubmit
src/stories/      the catalogue. Every component, in all three scripts, side by side.
```

## Using it from an app

Components read CSS custom properties and render unstyled without them, so the consuming
app must import the token sheet **and** point Tailwind at this package's source:

```css
@import 'tailwindcss';
@source '../../../packages/ui/src';   /* required, and fails silently if omitted */

@import '@sarana/ui/tokens.css';
```

Tailwind v4 scans the project it is invoked from. Without `@source`, none of the utilities
these components reference are generated, and the app renders as unstyled HTML with no
error anywhere. It is the first thing to check.

Set the surface on `<html>`: `data-theme="dark"` for the console, `data-theme="light"` for
the public dashboard. Both are supported in both apps; the defaults are chosen, not
accidental — operations rooms run dark and save real battery on an OLED handset, and a
public dashboard is read in daylight, screenshotted into articles, and printed.

## Editing a token

`src/tokens/*.ts` is the source. Regenerate after any change:

```bash
pnpm --filter @sarana/ui tokens:generate
```

`test:tokens-sync` diffs the generated files against their source and fails CI with the
stale paths, so forgetting is caught rather than shipped as three token tables that
disagree.

## The gates

```bash
pnpm --filter @sarana/ui test                 # 64 unit tests
pnpm --filter @sarana/ui test:contrast        # 79 token pairings, WCAG 2.2 AA
pnpm --filter @sarana/ui test:i18n-overflow   # 15 slots x 3 scripts
pnpm --filter @sarana/ui test:a11y            # axe over all 33 stories
pnpm --filter @sarana/ui test:tokens-sync     # generated files vs source
pnpm --filter @sarana/ui storybook:build
```

Two notes on what these do and do not prove:

- **`test:a11y` disables axe's `color-contrast` rule.** jsdom has no cascade, so it cannot
  evaluate colour at all; disabling it explicitly is honest, and colour is gated by
  `test:contrast`, which is stronger — it covers both surfaces and every state rather than
  only what happens to be on screen.
- **`test:i18n-overflow` is a width model, not a browser.** It estimates rendered width
  from code-point count, a per-script mean advance and the per-script size uplift, and
  measures that against each slot's real budget. It catches a translation growing past its
  slot. It does not catch a layout that breaks for another reason — that needs the visual
  regression suite, which is not built.

## Why the arbitrary-value class syntax

Components write `text-[var(--text-muted)]` rather than the shorter `text-text-muted` the
theme bridge also allows. It is more verbose on purpose: it names the exact token, so every
component's dependency on a token is greppable, and it works whether or not the consuming
app pulled in the `@theme` block.

One place this matters more than style: **never build a class by concatenation.** Tailwind
extracts utilities by scanning source for literal strings, so `'bg-[var(--sev-' + level +
'-bg)]'` produces a class that is never generated — and it fails silently, in the build, on
the component whose colour is load-bearing. `severity-pill.tsx` keeps a literal lookup table
for exactly this reason.
