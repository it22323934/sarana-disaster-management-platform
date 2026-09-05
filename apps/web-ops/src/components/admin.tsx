'use client';

/**
 * `/admin` — the template review gate, and the cost schedules.
 *
 * The template gate is the useful half. All twelve seeded templates are `DRAFT` with no
 * reviewer signatures, deliberately, and until each one is signed in Sinhala **and** Tamil
 * and then published, no alert can be dispatched from it. This screen is where that
 * happens.
 *
 * Three rules the screen holds:
 *
 * **The reviewer is the signed-in user, always.** `POST /templates/{id}/review` takes only
 * a language; the identity comes from the token. There is no field here to attribute a
 * review to somebody else, because a review somebody else can attribute to you is not a
 * review.
 *
 * **The language is chosen explicitly, never inferred.** Someone who reads both still has
 * to say which one they are signing for. Two separate buttons, each naming its language in
 * that language.
 *
 * **Publish is unreachable until both signatures exist.** The database predicate refuses
 * it anyway, and the server checks before that — this is the third layer, and it exists so
 * a reviewer never presses a button that was always going to fail.
 *
 * The reviewer reads the body in the language they are signing, with `lang` set, so it
 * renders in the right face rather than in whatever the interface locale happens to be.
 */

import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  LKRAmount,
  ReferenceCode,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  cn,
} from '@sarana/ui';
import { LOCALE_NAMES } from '@sarana/ts-shared/i18n';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { gatewayFetch } from '../lib/gateway-client';
import { useCostSchedules, useTemplates } from '../lib/queries';
import type { AlertTemplate, ScheduleLine } from '../lib/schemas';
import { ErrorPanel } from './degraded';

export function Admin() {
  const t = useTranslations('admin');

  return (
    <div className="flex flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold">{t('title')}</h1>

      <Tabs defaultValue="templates">
        <TabsList>
          <TabsTrigger value="templates">{t('templates')}</TabsTrigger>
          <TabsTrigger value="schedules">{t('schedules')}</TabsTrigger>
        </TabsList>
        <TabsContent value="templates">
          <TemplateReview />
        </TabsContent>
        <TabsContent value="schedules">
          <CostSchedules />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function TemplateReview() {
  const t = useTranslations('admin');
  const templates = useTemplates();

  if (templates.isPending) return <Skeleton className="h-64" />;
  if (templates.isError) return <ErrorPanel error={templates.error} />;

  const rows = templates.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-[var(--text-muted)]">{t('templatesHint')}</p>
      {rows.length === 0 ? (
        <EmptyState title={t('noTemplates')} description={t('noTemplatesHint')} />
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((template) => (
            <li key={template.id}>
              <TemplateCard template={template} onChanged={() => void templates.refetch()} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TemplateCard({
  template,
  onChanged,
}: {
  readonly template: AlertTemplate;
  readonly onChanged: () => void;
}) {
  const t = useTranslations('admin');
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<unknown>(null);

  const signedSi = template.reviewed_by_si !== null;
  const signedTa = template.reviewed_by_ta !== null;
  const published = template.status === 'PUBLISHED';
  const publishable = signedSi && signedTa && !published;

  async function review(language: 'si' | 'ta'): Promise<void> {
    setBusy(language);
    setFailure(null);
    try {
      await gatewayFetch(`templates/${template.id}/review`, {
        method: 'POST',
        body: { language },
        idempotencyKey: `review-${template.id}-${language}`,
      });
      onChanged();
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(null);
    }
  }

  async function publish(): Promise<void> {
    setBusy('publish');
    setFailure(null);
    try {
      await gatewayFetch(`templates/${template.id}/publish`, {
        method: 'POST',
        body: {},
        idempotencyKey: `publish-${template.id}`,
      });
      onChanged();
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(null);
    }
  }

  return (
    <article
      data-template-status={template.status}
      className={cn(
        'flex flex-col gap-3 rounded-[var(--radius-default)] border p-4',
        published
          ? 'border-[var(--verified)] bg-[var(--surface-card)]'
          : 'border-[var(--divider)] bg-[var(--surface-card)]',
      )}
    >
      <header className="flex flex-wrap items-baseline gap-3">
        <ReferenceCode code={template.code} kind={template.hazard_type} />
        <Badge tone={published ? 'verified' : 'pending'}>{template.status}</Badge>
        <span className="text-2xs text-[var(--text-muted)]">{template.severity}</span>
      </header>

      {/* The body in each language, with `lang` set so a reviewer reads it in the right
          face — and so a screen reader announces it in the right voice. Reviewing Tamil
          text rendered in the Latin fallback is reviewing something other than what
          ships. */}
      <div className="grid gap-3 lg:grid-cols-3">
        {(['si', 'ta', 'en'] as const).map((locale) => (
          <div key={locale} className="flex flex-col gap-1">
            <span className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
              {LOCALE_NAMES[locale]}
            </span>
            <p lang={locale === 'en' ? 'en-LK' : `${locale}-LK`} className="text-sm">
              {template.body[locale]}
            </p>
          </div>
        ))}
      </div>

      {failure ? <ErrorPanel error={failure} /> : null}

      <div className="flex flex-wrap items-center gap-3 border-t border-[var(--divider)] pt-3">
        <SignatureState signed={signedSi} label={LOCALE_NAMES.si} />
        <SignatureState signed={signedTa} label={LOCALE_NAMES.ta} />

        {!published ? (
          <>
            <Button
              size="sm"
              variant="secondary"
              lang="si-LK"
              disabled={signedSi || busy !== null}
              busy={busy === 'si'}
              busyLabel={t('sign', { language: LOCALE_NAMES.si })}
              onClick={() => review('si')}
            >
              {t('sign', { language: LOCALE_NAMES.si })}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              lang="ta-LK"
              disabled={signedTa || busy !== null}
              busy={busy === 'ta'}
              busyLabel={t('sign', { language: LOCALE_NAMES.ta })}
              onClick={() => review('ta')}
            >
              {t('sign', { language: LOCALE_NAMES.ta })}
            </Button>
            <Button
              size="sm"
              variant="primary"
              // Unreachable until both signatures exist. The server refuses it and so does
              // a database predicate; this is the third layer, and it is here so a
              // reviewer never presses a button that was always going to fail.
              disabled={!publishable || busy !== null}
              busy={busy === 'publish'}
              busyLabel={t('publish')}
              onClick={publish}
            >
              {t('publish')}
            </Button>
          </>
        ) : null}
      </div>

      {!published && !publishable ? (
        <p className="text-2xs text-[var(--text-muted)]">{t('needsBothSignatures')}</p>
      ) : null}
    </article>
  );
}

function SignatureState({
  signed,
  label,
}: {
  readonly signed: boolean;
  readonly label: string;
}) {
  const t = useTranslations('admin');
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-xs',
        signed ? 'text-[var(--verified)]' : 'text-[var(--pending)]',
      )}
    >
      {/* A tick or a bar, so the state is not carried by green-versus-slate alone. */}
      <svg viewBox="0 0 12 12" className="size-3 shrink-0" aria-hidden="true">
        <path
          d={signed ? 'M2.5 6.5 5 9l4.5-5.5' : 'M6 2.5v5M6 9.2v.3'}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {signed ? t('signed', { language: label }) : t('unsigned', { language: label })}
    </span>
  );
}

/**
 * The cost schedules, with the published formula for every line.
 *
 * Read-only. A schedule is what every entitlement in the system is calculated from, and
 * changing one from a console during an incident would silently re-price work already
 * done. Versions are added by migration, deliberately.
 */
function CostSchedules() {
  const t = useTranslations('admin');
  const disbursement = useTranslations('disbursement');
  const schedules = useCostSchedules();

  if (schedules.isPending) return <Skeleton className="h-64" />;
  if (schedules.isError) return <ErrorPanel error={schedules.error} />;

  const lines = (schedules.data ?? []).flatMap((schedule) =>
    schedule.lines.map((line) => ({ ...line, version: schedule.version })),
  );

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-[var(--text-muted)]">{t('schedulesHint')}</p>
      <DataTable<ScheduleLine & { version: string }>
        caption={t('schedules')}
        rows={lines}
        rowKey={(line) => `${line.version}-${line.id}`}
        height="calc(100vh - 22rem)"
        empty={<EmptyState title={t('noSchedules')} description={t('noSchedulesHint')} />}
        columns={[
          {
            key: 'version',
            header: disbursement('scheduleVersion'),
            width: '9rem',
            cell: (line) => (
              <span data-sarana-datum="" className="font-mono text-xs">
                {line.version}
              </span>
            ),
          },
          {
            key: 'category',
            header: disbursement('category'),
            width: '12rem',
            cell: (line) => (
              <span className="text-xs">
                {line.category}
                {line.subcategory ? ` · ${line.subcategory}` : null}
              </span>
            ),
          },
          {
            key: 'rate',
            header: t('rate'),
            width: '12rem',
            numeric: true,
            cell: (line) => <LKRAmount cents={line.rate_lkr_cents} />,
          },
          {
            key: 'cap',
            header: t('cap'),
            width: '12rem',
            numeric: true,
            cell: (line) =>
              line.cap_lkr_cents === null ? '—' : <LKRAmount cents={line.cap_lkr_cents} />,
          },
          {
            key: 'formula',
            header: disbursement('formula'),
            // The published formula, verbatim. It is what a household is entitled to read
            // alongside the figure they are told, which is the difference between a number
            // that is contestable and one that is merely announced.
            cell: (line) => (
              <span data-sarana-datum="" className="font-mono text-2xs">
                {JSON.stringify(line.formula)}
              </span>
            ),
          },
        ]}
      />
    </div>
  );
}
