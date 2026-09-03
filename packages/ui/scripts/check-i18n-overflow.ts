/**
 * The i18n overflow gate. `pnpm --filter @sarana/ui test:i18n-overflow`.
 *
 * Layout that breaks in Tamil is a bug of the same severity as a broken build, so this
 * runs in CI and exits non-zero.
 *
 * It measures the estimated rendered width of every gated string in all three scripts
 * against the width of the slot it has to fit in. See `src/stories/overflow-budgets.ts`
 * for the model and for what it does and does not catch.
 *
 * The report prints every slot, not only the failures, with the ratio against the English
 * baseline - because the number a reviewer wants is not "does it fit" but "how much
 * longer is Tamil here", which is what tells you whether the slot has any headroom left.
 */

import { LOCALES } from '@sarana/ts-shared/i18n';

import {
  OVERFLOW_SLOTS,
  measure,
  type OverflowResult,
} from '../src/stories/overflow-budgets.js';

function bar(result: OverflowResult): string {
  const used = result.estimatedPx / result.availablePx;
  const filled = Math.min(20, Math.round(used * 20));
  return `${'#'.repeat(filled)}${'.'.repeat(Math.max(0, 20 - filled))} ${Math.round(used * 100)}%`;
}

function main(): void {
  const failures: OverflowResult[] = [];

  console.log(
    `SARANA i18n overflow gate - ${OVERFLOW_SLOTS.length} slots x ${LOCALES.length} scripts\n`,
  );

  for (const slot of OVERFLOW_SLOTS) {
    const results = LOCALES.map((locale) => measure(slot, locale));
    const baseline = results.find((result) => result.locale === 'en');

    console.log(`${slot.name}`);
    console.log(`  budget ${slot.budgetPx}px x ${slot.lines} line(s) at ${slot.size}`);
    for (const result of results) {
      const ratio =
        baseline && baseline.estimatedPx > 0
          ? ` (${(result.estimatedPx / baseline.estimatedPx).toFixed(2)}x en)`
          : '';
      console.log(
        `    ${result.locale}  ${bar(result)}  ${result.estimatedPx}px` +
          `${ratio}${result.fits ? '' : '  <-- OVERFLOWS'}`,
      );
      if (!result.fits) failures.push(result);
    }
    console.log('');
  }

  if (failures.length > 0) {
    console.error(`${failures.length} string(s) overflow their slot:\n`);
    for (const failure of failures) {
      console.error(
        `  ${failure.slot} [${failure.locale}]\n` +
          `    "${failure.text}"\n` +
          `    needs ~${failure.estimatedPx}px, has ${failure.availablePx}px\n`,
      );
    }
    console.error(
      'Fix by shortening the translation, widening the slot, or allowing another line ' +
        'in src/stories/overflow-budgets.ts. Do not shrink the type: 13px is the floor.',
    );
    process.exitCode = 1;
    return;
  }

  console.log(`All ${OVERFLOW_SLOTS.length * LOCALES.length} strings fit their slots.`);
}

main();
