/**
 * The rules the domain components enforce, held as tests.
 *
 * These are not rendering smoke tests. Each one asserts a property that, if it stopped
 * holding, would let the interface tell a user something untrue.
 */

import { formatDateTime } from '@sarana/ts-shared/format';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { SEVERITY_LABELS, SEVERITY_LEVELS } from '../tokens/severity.js';
import { LocalisedText, TranslationCompleteness } from './localised-text.js';
import { SeverityPill } from './severity-pill.js';
import { HashDisplay, LKRAmount, RelativeTime, groupHash } from './datum.js';
import { ConfidenceMeter, MockDataBadge, OfflineIndicator } from './trust.js';
import {
  GATE_PERSISTENT_AFTER_SECONDS,
  GATE_PROMINENT_AFTER_SECONDS,
  PendingGateBanner,
  urgencyFor,
} from './pending-gate-banner.js';
import { GNDivisionPicker } from './gn-division-picker.js';

const NOW = new Date('2025-11-27T23:00:00Z');

describe('SeverityPill', () => {
  it('renders the word as well as the colour, at every level and in every language', () => {
    // Colour alone is unreadable to roughly 8% of men, and the tints are within 1.06:1 of
    // each other in greyscale - measured in tokens.test.ts. The word is the carrier.
    for (const level of SEVERITY_LEVELS) {
      for (const locale of ['si', 'ta', 'en'] as const) {
        const { unmount } = render(<SeverityPill level={level} locale={locale} />);
        expect(screen.getByText(SEVERITY_LABELS[level][locale])).toBeDefined();
        unmount();
      }
    }
  });

  it('renders a shape alongside the word', () => {
    // The third carrier. It is what separates the levels for a reader who has the label
    // read to them out of order, or who is looking at a printed monochrome report.
    const { container } = render(<SeverityPill level={3} locale="en" />);
    expect(container.querySelector('svg path')).not.toBeNull();
  });

  it('puts the level in the DOM as data, not only as a colour', () => {
    // So a test, an export or a screenshot diff can read the grade without sampling a
    // pixel and guessing which token it came from.
    const { container } = render(<SeverityPill level={4} locale="en" />);
    expect(container.querySelector('[data-severity="4"]')).not.toBeNull();
    expect(container.querySelector('[data-severity-name="severe"]')).not.toBeNull();
  });

  it('still renders a word when the caller overrides the label', () => {
    render(<SeverityPill level={2} locale="en" label="Flood watch" />);
    expect(screen.getByText('Flood watch')).toBeDefined();
  });
});

describe('LocalisedText', () => {
  const value = { si: 'මහනුවර', ta: 'கண்டி', en: 'Kandy' };

  it('sets lang, which is what selects the script face and the screen reader voice', () => {
    const { container } = render(<LocalisedText value={value} locale="ta" />);
    const element = container.querySelector('[lang]');
    expect(element?.getAttribute('lang')).toBe('ta-LK');
    expect(element?.textContent).toBe('கண்டி');
  });

  it('marks an incomplete value instead of silently rendering the locale it has', () => {
    // A payload missing a locale is a server-side bug - the API contract requires all
    // three and a CHECK constraint enforces it. Rendering it silently would hide that.
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { container } = render(
      // Deliberately invalid, which is why the cast is here.
      <LocalisedText value={{ en: 'Kandy' } as typeof value} locale="en" />,
    );
    expect(container.querySelector('[data-sarana-incomplete-translation]')).not.toBeNull();
    expect(errors).toHaveBeenCalled();
    errors.mockRestore();
  });
});

describe('TranslationCompleteness', () => {
  it('names the language that is missing, not just that one is', () => {
    // A reviewer about to sign off a two-language alert needs to know which script is
    // absent before they reach the button.
    render(
      <TranslationCompleteness
        present={['en', 'si']}
        completeLabel="Complete"
        incompleteLabel={(missing) => `Missing: ${missing}`}
      />,
    );
    expect(screen.getByText('Missing: தமிழ்')).toBeDefined();
  });

  it('reports complete only when all three are present', () => {
    render(
      <TranslationCompleteness
        present={['en', 'si', 'ta']}
        completeLabel="Complete"
        incompleteLabel={(missing) => `Missing: ${missing}`}
      />,
    );
    expect(screen.getByText('Complete')).toBeDefined();
  });
});

describe('the data primitives', () => {
  it('formats an amount from integer minor units', () => {
    render(<LKRAmount cents={125_000_00} />);
    expect(screen.getByText('LKR 125,000.00')).toBeDefined();
  });

  it('labels a voided amount for a screen reader, not only with a strikethrough', () => {
    // A strikethrough does not reach assistive technology. "LKR 25,000" read out with no
    // qualification from a reversed entry answers "how much was this household paid"
    // wrongly.
    const { container } = render(
      <LKRAmount cents={25_000_00} voided voidedLabel="reversed" />,
    );
    expect(container.textContent).toContain('reversed');
  });

  it('groups a hash in fours so it can be compared character by character', () => {
    expect(groupHash('9f2b1c4e')).toBe('9f2b 1c4e');
  });

  it('keeps the whole digest available even when the display is truncated', async () => {
    // A partial hash pasted into the verifier is a failed check that looks like a
    // tampered ledger.
    const hash = 'a'.repeat(64);
    const write = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: write } });

    render(<HashDisplay hash={hash} copyLabel="Copy" copiedLabel="Copied" />);
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }));
    expect(write).toHaveBeenCalledWith(hash);
  });

  it('shows the absolute time alongside the relative one', () => {
    // A stale "12 minutes ago" on a page open for an hour is a real hazard during an
    // incident, and a tooltip does not open on the handset a GN officer is holding.
    const { container } = render(
      <RelativeTime value="2025-11-27T22:18:00Z" now={NOW} locale="en" />,
    );
    expect(container.querySelector('time')?.getAttribute('dateTime')).toBe(
      '2025-11-27T22:18:00.000Z',
    );
    // Compared against the formatter rather than a literal, so the assertion tracks the
    // one definition of how a Colombo timestamp is written.
    expect(container.textContent).toContain(formatDateTime('2025-11-27T22:18:00Z', 'en'));
  });
});

describe('the honesty components', () => {
  it('states in the badge that the data is simulated, in the active language', () => {
    render(<MockDataBadge locale="ta" source="dept-meteorology" />);
    expect(screen.getByText('உருவகப்படுத்தப்பட்ட தரவு')).toBeDefined();
    expect(screen.getByText('(dept-meteorology)')).toBeDefined();
  });

  it('renders the consequence beside the confidence number, not behind a hover', () => {
    // A confidence number with no consequence attached teaches an operator to ignore it.
    render(
      <ConfidenceMeter
        value={0.62}
        band="medium"
        bandLabel="Medium"
        consequence="Routed to human review"
      />,
    );
    expect(screen.getByText('Routed to human review')).toBeDefined();
    expect(screen.getByText('62%')).toBeDefined();
  });

  it('says how much work is queued, not only that the device is offline', () => {
    // "Offline" alone reads as "your work is lost", which is the one thing it must never
    // imply on an offline-first platform.
    render(
      <OfflineIndicator
        online={false}
        queued={3}
        onlineLabel="Online"
        offlineLabel="Offline"
        queuedLabel={(count) => `${count} reports waiting`}
      />,
    );
    expect(screen.getByText('3 reports waiting')).toBeDefined();
  });
});

describe('PendingGateBanner', () => {
  it('escalates on the age of the oldest item, at the two documented thresholds', () => {
    expect(urgencyFor(GATE_PROMINENT_AFTER_SECONDS - 1)).toBe('waiting');
    expect(urgencyFor(GATE_PROMINENT_AFTER_SECONDS)).toBe('prominent');
    expect(urgencyFor(GATE_PERSISTENT_AFTER_SECONDS - 1)).toBe('prominent');
    expect(urgencyFor(GATE_PERSISTENT_AFTER_SECONDS)).toBe('persistent');
  });

  it('interrupts a screen reader only once the wait is persistent', () => {
    // A gate that arrived ten seconds ago should not interrupt whatever the operator is
    // reading; one that has waited five minutes should.
    const { container: fresh } = render(
      <PendingGateBanner
        kind="dispatch"
        count={1}
        oldestWaitingSince="2025-11-27T22:59:30Z"
        now={NOW}
        title={(count) => `${count} waiting`}
        ageLabel={(seconds) => `${seconds}s`}
        action={null}
      />,
    );
    expect(fresh.querySelector('[role="status"]')).not.toBeNull();

    const { container: stale } = render(
      <PendingGateBanner
        kind="dispatch"
        count={1}
        oldestWaitingSince="2025-11-27T22:50:00Z"
        now={NOW}
        title={(count) => `${count} waiting`}
        ageLabel={(seconds) => `${seconds}s`}
        action={null}
      />,
    );
    expect(stale.querySelector('[role="alert"]')).not.toBeNull();
    expect(stale.querySelector('[data-gate-urgency="persistent"]')).not.toBeNull();
  });

  it('renders nothing when nothing is waiting', () => {
    // A gate banner showing zero is chrome, and chrome that is always present is chrome
    // that stops being read.
    const { container } = render(
      <PendingGateBanner
        kind="disbursement"
        count={0}
        oldestWaitingSince={NOW.toISOString()}
        now={NOW}
        title={(count) => `${count} waiting`}
        ageLabel={() => ''}
        action={null}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('escalates in weight, never into a severity colour', () => {
    // Turning the banner red at five minutes would put a hazard colour on a workflow
    // state and break the rule the whole palette exists to keep.
    const { container } = render(
      <PendingGateBanner
        kind="dispatch"
        count={1}
        oldestWaitingSince="2025-11-27T22:50:00Z"
        now={NOW}
        title={(count) => `${count} waiting`}
        ageLabel={() => ''}
        action={null}
      />,
    );
    const className = (container.firstElementChild as HTMLElement).className;
    expect(className).toContain('--pending');
    expect(className).not.toMatch(/--sev-\d/);
  });
});

describe('GNDivisionPicker', () => {
  const divisions = [
    {
      code: 'LK-11-03-001',
      name: { si: 'පල්ලේකැලේ', ta: 'பள்ளேகலை', en: 'Pallekele' },
    },
    {
      code: 'LK-11-03-002',
      name: { si: 'කඩවත', ta: 'கடவத்தை', en: 'Kadawatha' },
    },
  ];

  it('finds a division by a name in a script the operator is not working in', async () => {
    // An officer typing in Sinhala has to find a division whose English name they have
    // never seen, and the other way round.
    const onChange = vi.fn();
    render(
      <GNDivisionPicker
        divisions={divisions}
        value={null}
        onChange={onChange}
        locale="en"
        label="Division"
        resultsLabel={(count) => `${count} results`}
      />,
    );

    const input = screen.getByRole('combobox');
    await userEvent.type(input, 'කඩවත');
    expect(screen.getByText('Kadawatha')).toBeDefined();
  });

  it('finds a division by its code, which is the identity', async () => {
    render(
      <GNDivisionPicker
        divisions={divisions}
        value={null}
        onChange={() => undefined}
        locale="en"
        label="Division"
        resultsLabel={(count) => `${count} results`}
      />,
    );
    await userEvent.type(screen.getByRole('combobox'), 'LK-11-03-002');
    expect(screen.getByText('Kadawatha')).toBeDefined();
  });

  it('shows the code alongside every name, because names are not unique', async () => {
    // Several divisions share a name and transliteration is not one-to-one, so a picker
    // that showed only names would let an operator choose the wrong Kadawatha.
    render(
      <GNDivisionPicker
        divisions={divisions}
        value={null}
        onChange={() => undefined}
        locale="en"
        label="Division"
        resultsLabel={(count) => `${count} results`}
      />,
    );
    await userEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('LK-11-03-001')).toBeDefined();
  });
});
