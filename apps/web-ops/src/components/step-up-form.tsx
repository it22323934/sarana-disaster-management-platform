'use client';

/**
 * `/totp` — proving who is at the keyboard, on its own screen.
 *
 * The gates collect the second factor inline, beside the button, and that is right for
 * them: the relationship between the code and the action is spatial rather than
 * remembered. This screen exists for the other case — a session whose step-up has expired
 * being sent somewhere to renew it, and a user who wants to step up *before* opening a
 * queue of decisions rather than in the middle of the first one.
 *
 * Three things it does and one it deliberately does not.
 *
 * **It says what a step-up is for, in plain words.** "Enter your code" tells somebody what
 * to type; it does not tell them why an application they are already signed into is asking
 * again. An operator who does not understand the rule experiences it as an obstruction and
 * looks for a way round it.
 *
 * **It says how long it lasts.** Five minutes, matching what `ledger-svc` and
 * `incident-svc` enforce. An approver who knows the window can decide whether to step up
 * now or at the gate; one who does not will be surprised at the gate every time.
 *
 * **It never submits on Enter.** Same rule as the dispatch gate. This screen does not
 * itself commit anything, but the habit is the point: on this platform, a six-digit code
 * plus a return key must never be a complete action.
 *
 * **It does not redirect anywhere on success.** A step-up is not a destination and the
 * user came from somewhere. Sending them to a default landing page would lose the queue
 * they were working; the screen confirms and offers `back`, which the browser has and this
 * component does not need to guess.
 */

import { Button, Input, cn } from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { Link } from '../i18n/routing';
import { stepUp } from '../lib/auth-actions';
import { STEP_UP_WINDOW_MINUTES } from '../lib/step-up';

const TOTP_LENGTH = 6;

export function StepUpForm() {
  const t = useTranslations('auth');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<'idle' | 'done'>('idle');
  const [failure, setFailure] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focused on load: this screen has exactly one thing to do on it.
  useEffect(() => inputRef.current?.focus(), []);

  const complete = /^\d{6}$/.test(code);

  async function submit(): Promise<void> {
    setBusy(true);
    setFailure(null);
    try {
      const result = await stepUp(code);
      if (result.ok) {
        setState('done');
        // Cleared from component state the moment it has been used. A TOTP code is
        // single-use and holding a spent one buys nothing.
        setCode('');
      } else {
        setFailure(result.message ?? t('stepUpFailed'));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-5 p-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold">{t('stepUpTitle')}</h1>
        <p className="text-sm text-[var(--text-muted)]">{t('stepUpWhy')}</p>
        <p className="text-xs text-[var(--text-muted)]">
          {t('stepUpWindow', { minutes: STEP_UP_WINDOW_MINUTES })}
        </p>
      </header>

      {state === 'done' ? (
        <div
          role="status"
          className={cn(
            'flex flex-col gap-3 rounded-[var(--radius-default)] border px-4 py-3',
            'border-[var(--verified)] text-[var(--verified)]',
          )}
        >
          <p className="text-sm font-medium">{t('stepUpDone')}</p>
          <p className="text-xs opacity-90">
            {t('stepUpWindow', { minutes: STEP_UP_WINDOW_MINUTES })}
          </p>
          {/* No redirect. The user came from a queue and the browser knows which one. */}
          <Button asChild variant="secondary" size="sm" className="self-start">
            <Link href="/ops">{t('stepUpContinue')}</Link>
          </Button>
        </div>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            // Never on Enter. This screen commits nothing, but the habit is the point:
            // six digits plus a return key is never a complete action on this platform.
            event.preventDefault();
          }}
        >
          <Input
            ref={inputRef}
            label={t('totpLabel')}
            description={t('totpPrompt')}
            value={code}
            onChange={(event) =>
              setCode(event.target.value.replace(/\D/g, '').slice(0, TOTP_LENGTH))
            }
            inputMode="numeric"
            autoComplete="one-time-code"
            datum
            maxLength={TOTP_LENGTH}
            error={failure ?? (code.length > 0 && !complete ? t('totpIncomplete') : undefined)}
          />
          <Button
            type="button"
            variant="primary"
            size="lg"
            disabled={!complete || busy}
            busy={busy}
            busyLabel={t('stepUpSubmit')}
            onClick={submit}
          >
            {t('stepUpSubmit')}
          </Button>
        </form>
      )}

      <p className="text-2xs text-[var(--text-muted)]">{t('stepUpNotAuthorisation')}</p>
    </div>
  );
}
