'use client';

/**
 * Sign in: credentials, then the second factor.
 *
 * Two steps in the UI even though `core-api` takes all three fields in one call. The
 * split is for the person, not the protocol: an operator reaches for their phone once
 * they have committed the password, and asking for all three at once means holding a
 * password on screen while they find the authenticator.
 *
 * The failure message is whatever the server sent, unchanged. `core-api` returns the same
 * text for "no such account" and "wrong password" on purpose — distinguishing them turns
 * this form into a way of enumerating who works for the state — and a console that
 * "helpfully" said which one was wrong would undo that.
 */

import { Button, Input } from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { signIn } from '../lib/auth-actions';
import { ErrorPanel } from './degraded';

const TOTP_LENGTH = 6;

export interface SignInFormProps {
  readonly locale: string;
}

export function SignInForm({ locale }: SignInFormProps) {
  const t = useTranslations('auth');

  const [step, setStep] = useState<'credentials' | 'totp'>('credentials');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [totp, setTotp] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      const form = new FormData();
      form.set('email', email);
      form.set('password', password);
      form.set('totpCode', totp);

      const result = await signIn(form);
      if (!result.ok) {
        setMessage(result.message ?? t('failedHint'));
        // Back to the first step: the code is single-use and retyping it against a
        // password that may itself be wrong wastes the operator's time twice.
        setStep('credentials');
        setTotp('');
        return;
      }
      // A full navigation rather than a client push, so the layout re-reads the principal
      // cookie the action just set and the navigation renders with the right scopes.
      window.location.assign(`/${locale}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center gap-6 p-6">
      <h1 className="text-xl font-semibold">{t('signIn')}</h1>

      {message ? (
        <ErrorPanel
          error={{ problem: { title: t('failed'), detail: message, correlation_id: '' } }}
        />
      ) : null}

      {step === 'credentials' ? (
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            setStep('totp');
          }}
        >
          <Input
            label={t('username')}
            description={t('emailHint')}
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <Input
            label={t('password')}
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <Button
            type="submit"
            variant="primary"
            size="lg"
            disabled={email.trim() === '' || password === ''}
          >
            {t('submit')}
          </Button>
        </form>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <h2 className="text-sm font-medium">{t('totpTitle')}</h2>
          <Input
            label={t('totpLabel')}
            description={t('totpPrompt')}
            inputMode="numeric"
            autoComplete="one-time-code"
            datum
            autoFocus
            maxLength={TOTP_LENGTH}
            value={totp}
            onChange={(event) =>
              setTotp(event.target.value.replace(/\D/g, '').slice(0, TOTP_LENGTH))
            }
          />
          <Button
            type="submit"
            variant="primary"
            size="lg"
            busy={busy}
            busyLabel={t('submit')}
            disabled={!/^\d{6}$/.test(totp)}
          >
            {t('submit')}
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setStep('credentials');
              setTotp('');
            }}
          >
            {t('back')}
          </Button>
        </form>
      )}
    </main>
  );
}
