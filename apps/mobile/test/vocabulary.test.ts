/**
 * The three vocabularies this app cannot import, checked against their source.
 *
 * TypeScript cannot import a Python enum, so the app copies the names out. A copy drifts
 * silently, and every one of these drifts is a 500 or a refused token rather than a
 * compile error - `sarana_shared.auth.scopes.Role`, the sync statuses in
 * `ledger_svc.domain.sync.OperationStatus`, and the damage categories in
 * `ledger_svc.repo.base`. So the Python files are read as text and compared.
 *
 * This is the same gate `tests/auth/test_console_scopes.py` runs in the other direction
 * for the ops console. Reading source rather than booting a service is deliberate: a
 * check that needs Docker is a check that gets skipped.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { ROLES } from '../src/auth/session.js';
import { OPERATION_STATUSES } from '../src/offline/log/types.js';
import { CAPABILITY_SCOPES, CAPABILITY_TTL_MS } from '../src/auth/capability.js';
import { MAX_BATCH } from '../src/offline/log/ordering.js';

const REPO = join(dirname(fileURLToPath(import.meta.url)), '../../..');

function read(path: string): string {
  return readFileSync(join(REPO, path), 'utf8');
}

/** `NAME = "VALUE"` members of a StrEnum, in declaration order. */
function enumMembers(source: string, className: string): string[] {
  const body = source.split(`class ${className}(StrEnum):`)[1] ?? '';
  const stopped = body.split(/\n\n\n/)[0] ?? '';
  return [...stopped.matchAll(/^\s{4}[A-Z_]+\s*=\s*"([^"]+)"/gm)].map((match) => match[1]!);
}

describe('roles', () => {
  it('carries exactly the roles sarana_shared.auth.scopes.Role defines', () => {
    const python = enumMembers(read('packages/py-shared/src/sarana_shared/auth/scopes.py'), 'Role');
    expect([...ROLES].sort()).toEqual([...python].sort());
  });
});

describe('sync statuses', () => {
  it('has a local status for every status the server can return', () => {
    // `applied` and `duplicate` both map to `synced` locally - a duplicate is the device
    // learning about a confirmation it never received, which is a success. Every other
    // server status has a local name of its own.
    const server = enumMembers(
      read('services/ledger-svc/src/ledger_svc/domain/sync.py'),
      'OperationStatus',
    );
    expect(server.sort()).toEqual(['applied', 'blocked', 'conflict', 'duplicate']);
    for (const status of ['blocked', 'conflict']) {
      expect(OPERATION_STATUSES).toContain(status);
    }
    expect(OPERATION_STATUSES).toContain('synced');
  });

  it('sends batches the server will accept', () => {
    // MAX_BATCH_OPERATIONS is the server's refusal threshold. The device sends 50, well
    // under it, so a batch is never refused for size - but if the server's cap ever drops
    // below the device's batch, every sync from every field device fails at once.
    const source = read('services/ledger-svc/src/ledger_svc/domain/sync.py');
    const cap = Number(/MAX_BATCH_OPERATIONS: Final = (\d+)/.exec(source)?.[1]);
    expect(cap).toBeGreaterThanOrEqual(MAX_BATCH);
  });
});

describe('the capability token', () => {
  it('has the same ttl and the same single scope as core-api mints', () => {
    const source = read('services/core-api/src/core_api/domain/auth/capability.py');
    const hours = Number(/CAPABILITY_TTL: Final = timedelta\(hours=(\d+)\)/.exec(source)?.[1]);
    expect(hours * 3_600_000).toBe(CAPABILITY_TTL_MS);

    const scopes = [...source.matchAll(/CAPABILITY_SCOPES: Final\[frozenset\[Scope\]\] = frozenset\(\{([^}]*)\}\)/g)]
      .flatMap((match) => [...(match[1] ?? '').matchAll(/Scope\.([A-Z_]+)/g)])
      .map((match) => match[1]!);
    expect(scopes).toEqual(['ASSESSMENT_WRITE']);
    // ASSESSMENT_WRITE's value, from the Scope enum, is what the device stores.
    expect([...CAPABILITY_SCOPES]).toEqual(['assessment:write']);
  });
});

describe('damage categories', () => {
  it('is the list the sync endpoint will accept', () => {
    // A category the server does not know is returned as a conflict with
    // `reason: unknown_category`, which jams that device's queue until a person looks at
    // it. Anything the Field Companion offers has to be on this list.
    const source = read('services/ledger-svc/src/ledger_svc/repo/base.py');
    const block = source.split('DAMAGE_CATEGORIES: Final[tuple[str, ...]] = (')[1] ?? '';
    const categories = [...(block.split(')')[0] ?? '').matchAll(/"([A-Z_]+)"/g)].map(
      (match) => match[1]!,
    );
    expect(categories).toEqual([
      'HOUSE_FULL',
      'HOUSE_PARTIAL',
      'HOUSEHOLD_GOODS',
      'LIVELIHOOD_TOOLS',
      'CROP',
      'LIVESTOCK',
      'FISHING_GEAR',
      'DEATH',
      'INJURY',
    ]);
  });
});
