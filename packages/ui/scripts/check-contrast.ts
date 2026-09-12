/**
 * The contrast gate. `pnpm --filter @sarana/ui test:contrast`.
 *
 * Prints every declared pairing with its measured ratio and exits non-zero on any
 * unexempted failure. It prints the passes too: a gate whose output is empty when it
 * succeeds gets no attention when the number of pairings quietly drops.
 */

import {
  EXEMPTIONS,
  evaluateAll,
  isExempt,
  unpairedTokens,
  type PairingResult,
} from '../src/tokens/pairings.js';

function line(result: PairingResult): string {
  const status = result.passes ? 'pass' : isExempt(result.name) ? 'exempt' : 'FAIL';
  const ratio = result.ratio.toFixed(2).padStart(6);
  return `  ${ratio} : ${String(result.floor).padEnd(3)} ${status.padEnd(6)} ${result.name}`;
}

function main(): void {
  const results = evaluateAll();
  const unexemptedFailures = results.filter((r) => !r.passes && !isExempt(r.name));
  const exemptedFailures = results.filter((r) => !r.passes && isExempt(r.name));
  const unpaired = unpairedTokens();

  console.log(`SARANA contrast gate - ${results.length} declared pairings\n`);
  for (const surface of ['dark', 'light'] as const) {
    console.log(`${surface} base:`);
    for (const result of results.filter((r) => r.surface === surface)) {
      console.log(line(result));
    }
    console.log('');
  }

  if (exemptedFailures.length > 0) {
    console.log(`${exemptedFailures.length} pairing(s) below floor by declared exemption:`);
    for (const exemption of EXEMPTIONS) {
      console.log(`  - ${exemption.name}\n      ${exemption.reason}`);
    }
    console.log('');
  }

  let failed = false;

  if (unpaired.length > 0) {
    failed = true;
    console.error(
      `${unpaired.length} colour token(s) appear in no declared pairing, so nothing ` +
        'measures them. Add a pairing in src/tokens/pairings.ts:',
    );
    for (const name of unpaired) console.error(`  - ${name}`);
    console.error('');
  }

  if (unexemptedFailures.length > 0) {
    failed = true;
    console.error(`${unexemptedFailures.length} pairing(s) below the WCAG 2.2 AA floor:`);
    for (const result of unexemptedFailures) {
      console.error(
        `  - ${result.name}: ${result.foreground} on ${result.background} ` +
          `is ${result.ratio.toFixed(2)}:1, needs ${result.floor}:1`,
      );
    }
    console.error('');
  }

  if (failed) {
    process.exitCode = 1;
    return;
  }
  console.log(
    `All ${results.length - exemptedFailures.length} gated pairings meet WCAG 2.2 AA.`,
  );
}

main();
