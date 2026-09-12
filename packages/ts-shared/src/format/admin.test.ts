import { describe, expect, it } from 'vitest';

import { adminLevel, covers, districtOf, dsOf, InvalidAdminCodeError } from './admin.js';

describe('adminLevel', () => {
  it('infers each level from the code shape', () => {
    expect(adminLevel('LK')).toBe('national');
    expect(adminLevel('LK-11')).toBe('district');
    expect(adminLevel('LK-11-03')).toBe('ds_division');
    expect(adminLevel('LK-11-03-045')).toBe('gn_division');
  });

  it('rejects a free-text place name', () => {
    expect(() => adminLevel('Batticaloa')).toThrow(InvalidAdminCodeError);
  });
});

describe('covers', () => {
  it('lets a district scope reach its own GN divisions', () => {
    expect(covers('LK-11', 'LK-11-03-045')).toBe(true);
  });

  it('does not let one district reach another', () => {
    expect(covers('LK-11', 'LK-12-03-045')).toBe(false);
  });

  it('rejects a truncated code rather than silently covering nothing', () => {
    // A silent `false` here reads as a permissions problem and sends someone hunting
    // in the wrong place. The malformed code is the real fault, so name it.
    expect(() => covers('LK-11-0', 'LK-11-03')).toThrow(InvalidAdminCodeError);
  });

  it('treats national scope as covering everything', () => {
    expect(covers('LK', 'LK-25-11-200')).toBe(true);
  });
});

describe('code extraction', () => {
  it('walks up the hierarchy from a GN code', () => {
    expect(dsOf('LK-11-03-045')).toBe('LK-11-03');
    expect(districtOf('LK-11-03-045')).toBe('LK-11');
  });

  it('refuses to invent a component that is not in the code', () => {
    expect(() => dsOf('LK-11')).toThrow(InvalidAdminCodeError);
  });
});
