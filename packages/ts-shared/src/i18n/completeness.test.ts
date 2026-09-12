import { describe, expect, it } from 'vitest';

import { checkCompleteness } from './completeness.js';

describe('checkCompleteness', () => {
  it('passes when all three locales carry the same keys', () => {
    const result = checkCompleteness({
      si: { action: { save: 'සුරකින්න' } },
      ta: { action: { save: 'சேமி' } },
      en: { action: { save: 'Save' } },
    });

    expect(result.complete).toBe(true);
    expect(result.keyCount).toBe(1);
  });

  it('catches the Ditwah failure: a warning with no Tamil', () => {
    const result = checkCompleteness({
      si: { alert: { headline: 'රතු අනතුරු ඇඟවීම' } },
      ta: {},
      en: { alert: { headline: 'Red alert' } },
    });

    expect(result.complete).toBe(false);
    expect(result.problems).toContainEqual({
      locale: 'ta',
      key: 'alert.headline',
      kind: 'missing',
    });
  });

  it('treats a whitespace-only string as missing, not present', () => {
    const result = checkCompleteness({
      si: { greeting: 'ආයුබෝවන්' },
      ta: { greeting: '   ' },
      en: { greeting: 'Hello' },
    });

    expect(result.complete).toBe(false);
    expect(result.problems[0]?.kind).toBe('blank');
  });
});
