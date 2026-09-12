'use client';

/**
 * Assigning and resolving a grievance.
 *
 * The brief asks `/grievances` for "queue, assignment, resolution". The queue was built;
 * these are the two actions on it, and both have a rule the console has to hold rather
 * than merely pass through.
 *
 * **The resolution is written in all three languages, and the console will not submit two.**
 * `ledger-svc` refuses a resolution that is not trilingual, and it is right to: the
 * resolution text is *sent to the household*. A Tamil-speaking family told only in Sinhala
 * why their claim was rejected has been told nothing. Making the button unreachable means
 * the refusal never happens, and the operator learns the rule from the form rather than
 * from a 400.
 *
 * **REJECTED needs the same explanation as RESOLVED.** It is a legitimate outcome and it
 * is the one where the explanation matters most: a household told only "rejected" has
 * learned nothing they can act on, and cannot tell a decision from a mistake.
 *
 * **The SLA clock is shown and never reset.** It started when the household complained. An
 * assignment does not restart it - the service is explicit about that - and the console
 * shows how long it has been running beside the assignment control, so passing a grievance
 * between offices is visibly not a way of keeping it fresh.
 */

import {
  Badge,
  Button,
  DialogContent,
  DialogRoot,
  DialogTrigger,
  Input,
  RadioGroup,
  RelativeTime,
  Textarea,
  cn,
} from '@sarana/ui';
import { LOCALES, LOCALE_NAMES, type Locale } from '@sarana/ts-shared/i18n';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { gatewayFetch } from '../lib/gateway-client';
import type { Grievance } from '../lib/schemas';
import { ErrorPanel } from './degraded';

/** BCP-47 tags, so each field renders in the script it is written in. */
const LANG_TAGS: Record<Locale, string> = { si: 'si-LK', ta: 'ta-LK', en: 'en-LK' };

/** The two ways a grievance closes. Both are dispositions; neither is a failure. */
export const RESOLUTION_STATUSES = ['RESOLVED', 'REJECTED'] as const;

export type ResolutionStatus = (typeof RESOLUTION_STATUSES)[number];

/** A DS division code, which is what an assignment routes to. */
const DS_CODE = /^LK-\d{2}-\d{2}$/;

export interface GrievanceWorkflowProps {
  readonly grievance: Grievance;
  readonly onChanged: () => void;
}

export function GrievanceWorkflow({ grievance, onChanged }: GrievanceWorkflowProps) {
  const t = useTranslations('grievances');

  return (
    <span className="flex flex-wrap gap-2">
      <AssignDialog grievance={grievance} onChanged={onChanged} />
      <ResolveDialog grievance={grievance} onChanged={onChanged} />
      {grievance.status === 'RESOLVED' || grievance.status === 'REJECTED' ? (
        <Badge tone="verified">{t('closed')}</Badge>
      ) : null}
    </span>
  );
}

function AssignDialog({ grievance, onChanged }: GrievanceWorkflowProps) {
  const t = useTranslations('grievances');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);

  const valid = DS_CODE.test(code.trim());

  async function assign(): Promise<void> {
    setBusy(true);
    setFailure(null);
    try {
      await gatewayFetch(`grievances/${grievance.id}/assign`, {
        method: 'POST',
        body: { ds_division_code: code.trim(), status: 'UNDER_REVIEW' },
        idempotencyKey: `assign-${grievance.id}-${code.trim()}`,
      });
      onChanged();
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <DialogRoot>
      <DialogTrigger asChild>
        <Button variant="secondary" size="sm">
          {t('assign')}
        </Button>
      </DialogTrigger>
      <DialogContent title={t('assignTitle')} description={t('assignHint')}>
        <div className="flex flex-col gap-4">
          {/* The clock, beside the control that might look like a way to stop it. */}
          <p className="text-xs text-[var(--text-muted)]">
            {t('raisedAt')}:{' '}
            {grievance.raised_at ? <RelativeTime value={grievance.raised_at} /> : '—'}
            {' · '}
            {t('slaDoesNotReset')}
          </p>

          <Input
            label={t('dsDivision')}
            description={t('dsDivisionHint')}
            datum
            value={code}
            onChange={(event) => setCode(event.target.value.toUpperCase())}
            error={code.length > 0 && !valid ? t('dsDivisionInvalid') : undefined}
          />

          {failure ? <ErrorPanel error={failure} /> : null}

          <Button
            variant="primary"
            disabled={!valid || busy}
            busy={busy}
            busyLabel={t('assign')}
            onClick={assign}
          >
            {t('assign')}
          </Button>
        </div>
      </DialogContent>
    </DialogRoot>
  );
}

function ResolveDialog({ grievance, onChanged }: GrievanceWorkflowProps) {
  const t = useTranslations('grievances');
  const [status, setStatus] = useState<ResolutionStatus>('RESOLVED');
  const [resolution, setResolution] = useState<Record<Locale, string>>({ si: '', ta: '', en: '' });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);

  // All three, or the button does not work. The service refuses a partial resolution and
  // the household is the reason: they are the one who receives this text.
  const missing = LOCALES.filter((locale) => resolution[locale].trim().length === 0);
  const complete = missing.length === 0;

  async function resolve(): Promise<void> {
    setBusy(true);
    setFailure(null);
    try {
      await gatewayFetch(`grievances/${grievance.id}/resolve`, {
        method: 'POST',
        body: {
          status,
          resolution: Object.fromEntries(
            LOCALES.map((locale) => [locale, resolution[locale].trim()]),
          ),
        },
        idempotencyKey: `resolve-${grievance.id}`,
      });
      onChanged();
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <DialogRoot>
      <DialogTrigger asChild>
        <Button variant="primary" size="sm">
          {t('resolve')}
        </Button>
      </DialogTrigger>
      <DialogContent title={t('resolveTitle')} description={t('resolveHint')}>
        <div className="flex flex-col gap-4">
          <RadioGroup
            legend={t('outcome')}
            value={status}
            onValueChange={(value) => setStatus(value as ResolutionStatus)}
            options={RESOLUTION_STATUSES.map((value) => ({
              value,
              label: t(`outcome_${value}`),
            }))}
          />

          {/* Rejection is where the explanation matters most: a household told only
              "rejected" cannot tell a decision from a mistake. */}
          {status === 'REJECTED' ? (
            <p className="text-xs text-[var(--sev-2-fg)]">{t('rejectionNeedsReason')}</p>
          ) : null}

          <div className="grid gap-3">
            {LOCALES.map((locale) => (
              <Textarea
                key={locale}
                label={LOCALE_NAMES[locale]}
                lang={LANG_TAGS[locale]}
                required
                rows={3}
                value={resolution[locale]}
                onChange={(event) =>
                  setResolution((current) => ({ ...current, [locale]: event.target.value }))
                }
              />
            ))}
          </div>

          <p
            className={cn(
              'text-xs',
              complete ? 'text-[var(--text-muted)]' : 'text-[var(--pending)]',
            )}
          >
            {complete
              ? t('allThreeWritten')
              : t('missingLanguages', {
                  languages: missing.map((locale) => LOCALE_NAMES[locale]).join(', '),
                })}
          </p>

          {failure ? <ErrorPanel error={failure} /> : null}

          <Button
            variant="primary"
            size="lg"
            disabled={!complete || busy}
            busy={busy}
            busyLabel={t('resolve')}
            onClick={resolve}
          >
            {t('resolve')}
          </Button>
        </div>
      </DialogContent>
    </DialogRoot>
  );
}
