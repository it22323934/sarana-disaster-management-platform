/**
 * Exponential backoff with jitter, capped at five minutes.
 *
 * The cap is the important number. Uncapped exponential backoff means a device that
 * failed six times in a cell-edge village is next going to try in an hour, long after the
 * officer has walked back into coverage - and the officer has no way to know that, so the
 * app looks broken while it waits. Five minutes is short enough that reconnecting is
 * always noticed within one cycle.
 *
 * Jitter is full jitter, not a small wobble: fifty devices in one division come back onto
 * one cell tower together when the power returns, and a synchronised retry from all of
 * them is a self-inflicted outage.
 */

/** First retry. Short enough to cover a single dropped packet without a visible pause. */
export const BASE_DELAY_MS = 1_000;

/** Never wait longer than this, however many times it has failed. */
export const MAX_DELAY_MS = 5 * 60_000;

export interface BackoffOptions {
  readonly baseMs?: number;
  readonly maxMs?: number;
  /** Injected in tests. `Math.random` in the app. */
  readonly random?: () => number;
}

/**
 * How long to wait before attempt number `attempt` (1 is the first retry).
 *
 * Full jitter: a uniform draw from `[0, ceiling]` where the ceiling doubles each time.
 * The expected delay is half the ceiling, which is why the ceiling is what the cap
 * applies to.
 */
export function delayFor(attempt: number, options: BackoffOptions = {}): number {
  const base = options.baseMs ?? BASE_DELAY_MS;
  const max = options.maxMs ?? MAX_DELAY_MS;
  const random = options.random ?? Math.random;

  if (attempt <= 0) return 0;

  // Computed on the exponent rather than by repeated doubling so a device that has been
  // failing for a day does not overflow into Infinity before the cap is applied.
  const exponent = Math.min(attempt - 1, 32);
  const ceiling = Math.min(base * 2 ** exponent, max);
  return Math.floor(random() * ceiling);
}

/**
 * A retry schedule that can be asked "may I go now?" without holding a timer.
 *
 * The sync engine is woken by several things it does not control - a foreground event, a
 * connectivity change, a background task - and each of them must respect the backoff
 * rather than reset it. Keeping the next-allowed time as state, instead of a `setTimeout`
 * the caller owns, is what makes that possible.
 */
export class RetrySchedule {
  #attempt = 0;
  #nextAllowedAt = 0;

  constructor(private readonly options: BackoffOptions = {}) {}

  get attempt(): number {
    return this.#attempt;
  }

  get nextAllowedAt(): number {
    return this.#nextAllowedAt;
  }

  mayRun(now: number): boolean {
    return now >= this.#nextAllowedAt;
  }

  /** How long the caller would have to wait. Shown in the status strip, in seconds. */
  waitMs(now: number): number {
    return Math.max(0, this.#nextAllowedAt - now);
  }

  /** Record a failure and schedule the next attempt. Returns the delay chosen. */
  fail(now: number): number {
    this.#attempt += 1;
    const delay = delayFor(this.#attempt, this.options);
    this.#nextAllowedAt = now + delay;
    return delay;
  }

  /**
   * Record a success.
   *
   * The schedule resets completely: the next failure starts from one second again. A
   * device that syncs successfully has demonstrated the network is there, and carrying
   * the old backoff forward would punish it for a problem that is over.
   */
  succeed(): void {
    this.#attempt = 0;
    this.#nextAllowedAt = 0;
  }

  /**
   * Clear the wait without clearing the attempt count.
   *
   * Used when the user pulls to refresh. Someone who has deliberately asked for a sync is
   * telling the app something it cannot detect - they have walked to the top of the hill -
   * and making them wait out a backoff they did not cause is the wrong answer.
   */
  allowNow(): void {
    this.#nextAllowedAt = 0;
  }
}
