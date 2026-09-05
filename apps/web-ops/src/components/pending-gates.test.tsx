/**
 * The pending gate banner, and the escalation the brief specifies by the minute.
 *
 * "Past 2 minutes it becomes prominent; past 5 it becomes persistent with an optional
 * sound. It is never dismissible while items are pending." Those thresholds are not
 * decoration: during Cyclone Ditwah the window between a division being identified as at
 * risk and needing to be evacuated was measured in minutes, and an approval sitting unseen
 * for five of them is the failure this whole surface exists to prevent.
 *
 * Tested with an injected clock rather than fake timers where possible. `PendingGateBanner`
 * takes a `now`, so the escalation can be asserted at exact ages without waiting; the
 * timer path is exercised separately, because a banner that only escalated when something
 * re-rendered would pass every assertion here and freeze on a screen nobody is touching -
 * which is precisely the screen this is for.
 */

import { render, screen, act } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  GATE_PERSISTENT_AFTER_SECONDS,
  GATE_PROMINENT_AFTER_SECONDS,
  PendingGateBanner,
  urgencyFor,
} from '@sarana/ui';

import en from '../../messages/en.json';

const NOW = new Date('2025-11-28T04:30:00Z');

function agedBy(seconds: number): string {
  return new Date(NOW.getTime() - seconds * 1000).toISOString();
}

function renderBanner(waitingSeconds: number, options: { onEnableSound?: () => void } = {}) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="Asia/Colombo" now={NOW}>
      <PendingGateBanner
        kind="dispatch"
        count={2}
        oldestWaitingSince={agedBy(waitingSeconds)}
        now={NOW}
        title={(count) => `${count} dispatches awaiting approval`}
        ageLabel={(seconds) => `waiting ${seconds}s`}
        action={<button type="button">Review now</button>}
        soundLabel="Enable sound"
        {...options}
      />
    </NextIntlClientProvider>,
  );
}

describe('the escalation thresholds', () => {
  it('is 2 minutes to prominent and 5 to persistent', () => {
    // Asserted as numbers as well as behaviour. A refactor that moved these would change
    // how long an approval can sit unnoticed, and that is a decision rather than a detail.
    expect(GATE_PROMINENT_AFTER_SECONDS).toBe(120);
    expect(GATE_PERSISTENT_AFTER_SECONDS).toBe(300);
  });

  it('escalates exactly at the boundary, not a second after it', () => {
    expect(urgencyFor(GATE_PROMINENT_AFTER_SECONDS - 1)).toBe('waiting');
    expect(urgencyFor(GATE_PROMINENT_AFTER_SECONDS)).toBe('prominent');
    expect(urgencyFor(GATE_PERSISTENT_AFTER_SECONDS - 1)).toBe('prominent');
    expect(urgencyFor(GATE_PERSISTENT_AFTER_SECONDS)).toBe('persistent');
  });
});

describe('what the banner does at each stage', () => {
  it('is a polite status under two minutes', () => {
    renderBanner(30);
    const banner = screen.getByRole('status');
    expect(banner).toHaveAttribute('data-gate-urgency', 'waiting');
    expect(banner).toHaveAttribute('aria-live', 'polite');
  });

  it('becomes prominent at two minutes without interrupting', () => {
    // Still `status`, not `alert`. A gate that arrived two minutes ago should grow on
    // screen; it should not interrupt whatever the operator is reading.
    renderBanner(GATE_PROMINENT_AFTER_SECONDS);
    const banner = screen.getByRole('status');
    expect(banner).toHaveAttribute('data-gate-urgency', 'prominent');
    expect(banner).toHaveAttribute('aria-live', 'polite');
  });

  it('becomes an assertive alert at five minutes', () => {
    // This is the point at which a screen reader user is interrupted, and it is the right
    // trade: five minutes is long enough that the interruption is the smaller cost.
    renderBanner(GATE_PERSISTENT_AFTER_SECONDS);
    const banner = screen.getByRole('alert');
    expect(banner).toHaveAttribute('data-gate-urgency', 'persistent');
    expect(banner).toHaveAttribute('aria-live', 'assertive');
  });

  it('offers no dismiss control at any stage', () => {
    // Not dismissible while anything is pending. A gate somebody can close is a queue.
    for (const age of [10, GATE_PROMINENT_AFTER_SECONDS, GATE_PERSISTENT_AFTER_SECONDS]) {
      const { unmount } = renderBanner(age);
      expect(screen.queryByRole('button', { name: /dismiss|close/i })).toBeNull();
      unmount();
    }
  });
});

describe('the sound control', () => {
  it('is offered only once the wait is persistent', () => {
    // Sound at ten seconds would be noise, and an operator who turns noise off has turned
    // off the thing that tells them about the five-minute case too.
    renderBanner(GATE_PROMINENT_AFTER_SECONDS, { onEnableSound: vi.fn() });
    expect(screen.queryByRole('button', { name: 'Enable sound' })).toBeNull();

    renderBanner(GATE_PERSISTENT_AFTER_SECONDS, { onEnableSound: vi.fn() });
    expect(screen.getByRole('button', { name: 'Enable sound' })).toBeInTheDocument();
  });

  it('is absent when no handler is passed, even at five minutes', () => {
    // The rule that kept it absent for the whole of file 20: offering a control that does
    // nothing is worse than not offering it, because an operator who enables it then
    // believes they will be told.
    renderBanner(GATE_PERSISTENT_AFTER_SECONDS);
    expect(screen.queryByRole('button', { name: 'Enable sound' })).toBeNull();
  });
});

describe('escalating on its own, with nothing touching the screen', () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: false }));
  afterEach(() => vi.useRealTimers());

  it('grows from waiting to persistent while the operator is away', () => {
    // The whole point. An operator who walked away must come back to a banner that has
    // grown, not to one still saying "waiting 20 seconds" ten minutes later. `now` is
    // deliberately not passed here, so the component runs its own interval.
    vi.setSystemTime(NOW);
    render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="Asia/Colombo" now={NOW}>
        <PendingGateBanner
          kind="disbursement"
          count={1}
          oldestWaitingSince={NOW.toISOString()}
          title={(count) => `${count} release awaiting approval`}
          ageLabel={(seconds) => `waiting ${seconds}s`}
          action={<button type="button">Review now</button>}
        />
      </NextIntlClientProvider>,
    );

    expect(screen.getByRole('status')).toHaveAttribute('data-gate-urgency', 'waiting');

    act(() => {
      vi.advanceTimersByTime(GATE_PROMINENT_AFTER_SECONDS * 1000);
    });
    expect(screen.getByRole('status')).toHaveAttribute('data-gate-urgency', 'prominent');

    act(() => {
      vi.advanceTimersByTime(
        (GATE_PERSISTENT_AFTER_SECONDS - GATE_PROMINENT_AFTER_SECONDS) * 1000,
      );
    });
    expect(screen.getByRole('alert')).toHaveAttribute('data-gate-urgency', 'persistent');
  });
});
