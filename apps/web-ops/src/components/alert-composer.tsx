'use client';

/**
 * `/ops/alerts/new` — composing an alert.
 *
 * Four rules run through this screen, and each one exists because of a specific way this
 * goes wrong:
 *
 * **Only PUBLISHED templates are offered.** All twelve seeded templates are `DRAFT` with
 * no reviewer signatures, deliberately: before an alert can be dispatched a human must
 * sign each language. The picker shows unpublished ones greyed out with the reason, rather
 * than hiding them — an operator who cannot find the flood template needs to know it is
 * awaiting a Tamil signature, not that it does not exist.
 *
 * **The preview is all three languages at once, with a segment count under each.** Not a
 * tabbed preview: a Sinhala rendering that runs to three segments is invisible behind a
 * tab, and three segments during a national fan-out is three times the cost, three times
 * the gateway queue, and three parts that can arrive out of order. The warning appears
 * while the operator is still choosing words, not after they send.
 *
 * **Free text is accepted and visibly flagged.** An operator must be able to say something
 * the templates do not cover. But it forces `PENDING_SIGNOFF` server-side, and the screen
 * says so inline with the reason, so nobody discovers it at the dispatch step.
 *
 * **The dry run is mandatory, and drafting is not sending.** This screen creates a draft
 * and stops. `POST /alerts/{id}/dispatch` with `dry_run` returns exact target counts and
 * the per-channel breakdown, and sending without seeing that is sending a life-safety
 * message to an unknown number of people — so the two are separate calls behind separate
 * screens. One button that drafted and sent is how a national fan-out happens by accident.
 */

import {
  Badge,
  Button,
  EmptyState,
  Input,
  Select,
  Skeleton,
  Textarea,
  cn,
} from '@sarana/ui';
import { LOCALES, LOCALE_NAMES, type Locale } from '@sarana/ts-shared/i18n';
import { countSegments, MAX_SEGMENTS } from '@sarana/ts-shared/format';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { gatewayFetch } from '../lib/gateway-client';
import { useHazardEvents, useTemplates } from '../lib/queries';
import { localised } from '@sarana/ts-shared/i18n';
import { Link } from '../i18n/routing';
import { alertSchema, type AlertTemplate } from '../lib/schemas';
import { AreaSelector } from './area-selector';
import { ErrorPanel } from './degraded';
import { QuietHoursNotice, quietHoursState } from './quiet-hours';

/** BCP-47 tags, so each preview renders in the right face and voice. */
const LANG_TAGS: Record<Locale, string> = { si: 'si-LK', ta: 'ta-LK', en: 'en-LK' };

/**
 * CAP severity words to the impact class the quiet-hours rule tests.
 *
 * Needed because the composer has no alert yet - there is nothing to ask the server
 * about - and the operator has to know *while writing* that a watch-level message at 2am
 * will be held until 06:00. Unknown maps to 0, which does not bypass: assuming the highest
 * class for a template whose severity nobody recognised would wake a district on the
 * strength of an unmatched string.
 */
const SEVERITY_CLASS: Record<string, number> = {
  EXTREME: 4,
  SEVERE: 3,
  MODERATE: 2,
  MINOR: 1,
  UNKNOWN: 0,
};

export function impactClassOf(template: AlertTemplate | null): number {
  return SEVERITY_CLASS[(template?.severity ?? '').toUpperCase()] ?? 0;
}

/**
 * Parameter names a template body refers to.
 *
 * Read from the body itself rather than from a separate declaration, so a template that
 * gains a placeholder cannot end up with an unfillable field nobody notices. Union across
 * all three languages: a placeholder present only in the Tamil body is still a parameter,
 * and missing it would render `{shelter_name}` literally to Tamil readers.
 */
export function parametersIn(template: AlertTemplate): string[] {
  const found = new Set<string>();
  for (const locale of LOCALES) {
    const body = template.body[locale] ?? '';
    for (const match of body.matchAll(/\{(\w+)\}/g)) {
      const name = match[1];
      if (name) found.add(name);
    }
  }
  return [...found].sort();
}

/** Substitute what the operator has filled in; leave the rest visible as placeholders. */
export function render(
  body: string,
  values: Readonly<Record<string, string>>,
): string {
  return body.replace(/\{(\w+)\}/g, (placeholder, name: string) => {
    const value = values[name];
    return value && value.trim().length > 0 ? value : placeholder;
  });
}

export function AlertComposer() {
  const t = useTranslations('compose');
  const alerts = useTranslations('alerts');
  const common = useTranslations('common');
  const locale = useLocale() as Locale;

  const templates = useTemplates();
  const events = useHazardEvents();
  const [templateCode, setTemplateCode] = useState<string>('');
  const [hazardEventId, setHazardEventId] = useState<string>('');
  const [drafted, setDrafted] = useState<{ id: string; cap_identifier: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [freeText, setFreeText] = useState<Partial<Record<Locale, string>>>({});
  const [divisions, setDivisions] = useState<string[]>([]);
  const [failure, setFailure] = useState<unknown>(null);

  const published = (templates.data ?? []).filter((template) => template.status === 'PUBLISHED');
  const selected = published.find((template) => template.code === templateCode) ?? null;
  const parameters = useMemo(() => (selected ? parametersIn(selected) : []), [selected]);

  /** The rendered message per language, with free text appended where there is any. */
  const previews = useMemo(() => {
    if (!selected) return null;
    return Object.fromEntries(
      LOCALES.map((locale) => {
        const base = render(selected.body[locale] ?? '', values);
        const extra = (freeText[locale] ?? '').trim();
        return [locale, extra.length > 0 ? `${base} ${extra}` : base];
      }),
    ) as Record<Locale, string>;
  }, [selected, values, freeText]);

  const usesFreeText = LOCALES.some((locale) => (freeText[locale] ?? '').trim().length > 0);

  /**
   * Create the draft.
   *
   * Deliberately does **not** dispatch. `POST /alerts` produces a draft; sending it is a
   * separate call behind a mandatory dry run, and putting both behind one button is how a
   * national fan-out happens by accident.
   */
  async function draft(): Promise<void> {
    if (!selected) return;
    setBusy(true);
    setFailure(null);
    try {
      const codes = divisions;

      const created = await gatewayFetch('alerts', {
        method: 'POST',
        body: {
          template_code: selected.code,
          hazard_event_id: hazardEventId,
          parameters: values,
          // The service resolves codes to ids. Sending both would be two sources of truth
          // for the same area and a chance for them to disagree.
          gn_division_ids: [],
          gn_division_codes: codes,
          effective_at: new Date().toISOString(),
          // Twelve hours. Long enough to cover a response shift, short enough that a
          // stale warning expires rather than sitting on a public feed indefinitely.
          expires_at: new Date(Date.now() + 12 * 3_600_000).toISOString(),
          free_text: usesFreeText ? freeText : null,
        },
        idempotencyKey: `draft-${selected.code}-${hazardEventId}-${codes.join(',')}`,
        schema: alertSchema.pick({ id: true, cap_identifier: true, status: true }),
      });
      setDrafted(created);
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }
  const overLimit =
    previews !== null &&
    LOCALES.some((locale) => !countSegments(previews[locale]).withinLimit);

  if (templates.isPending) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-20" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (templates.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={templates.error} />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <h1 className="text-xl font-semibold">{t('title')}</h1>

      {published.length === 0 ? (
        // Not an error and not an empty list: the templates exist and are waiting for a
        // human signature in each language. Saying which is the useful part.
        <EmptyState
          title={t('noPublished')}
          description={t('noPublishedHint')}
          action={
            <ul className="mt-2 flex flex-col gap-1 text-xs">
              {(templates.data ?? []).map((template) => (
                <li key={template.id} className="flex items-center gap-2">
                  <span data-sarana-datum="" className="font-mono">
                    {template.code}
                  </span>
                  <Badge tone="pending">{template.status}</Badge>
                  <span className="text-[var(--text-muted)]">
                    {template.reviewed_by_si === null || template.reviewed_by_ta === null
                      ? t('awaitingSignature')
                      : t('awaitingPublish')}
                  </span>
                </li>
              ))}
            </ul>
          }
        />
      ) : (
        <>
          <Select
            label={t('template')}
            placeholder={t('templateHint')}
            value={templateCode}
            onValueChange={(code) => {
              setTemplateCode(code);
              setValues({});
            }}
            options={published.map((template) => ({
              value: template.code,
              label: `${template.code} · ${template.severity}`,
            }))}
          />

          {selected ? (
            <>
              <section className="flex flex-col gap-3">
                <h2 className="text-sm font-medium">{t('parameters')}</h2>
                {parameters.length === 0 ? (
                  <p className="text-xs text-[var(--text-muted)]">{t('noParameters')}</p>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {parameters.map((name) => (
                      <Input
                        key={name}
                        label={name}
                        value={values[name] ?? ''}
                        onChange={(event) =>
                          setValues((current) => ({ ...current, [name]: event.target.value }))
                        }
                      />
                    ))}
                  </div>
                )}
              </section>

              <Preview previews={previews} />

              <section className="flex flex-col gap-3">
                <h2 className="text-sm font-medium">{t('freeText')}</h2>
                {/* Accepted rather than refused — an operator must be able to say
                    something the templates do not cover — but never without a human
                    seeing it first, and the screen says so before they commit to it. */}
                <p
                  className={cn(
                    'rounded-[var(--radius-default)] border px-3 py-2 text-xs',
                    usesFreeText
                      ? 'border-[var(--pending)] text-[var(--pending)]'
                      : 'border-[var(--divider)] text-[var(--text-muted)]',
                  )}
                >
                  {t('freeTextForcesSignoff')}
                </p>
                <div className="grid gap-3 lg:grid-cols-3">
                  {LOCALES.map((locale) => (
                    <Textarea
                      key={locale}
                      label={LOCALE_NAMES[locale]}
                      lang={LANG_TAGS[locale]}
                      rows={3}
                      value={freeText[locale] ?? ''}
                      onChange={(event) =>
                        setFreeText((current) => ({ ...current, [locale]: event.target.value }))
                      }
                    />
                  ))}
                </div>
              </section>

              {/* Which event this alert is about. `POST /alerts` requires it, and until
                  `GET /hazard-events` existed nothing could supply one — an operator could
                  compose and check a message and then had no way to name the event. */}
              <Select
                label={t('hazardEvent')}
                placeholder={t('hazardEventHint')}
                value={hazardEventId}
                onValueChange={setHazardEventId}
                options={(events.data ?? []).map((hazard) => ({
                  value: hazard.id,
                  label: `${localised(hazard.name, 'en')} · ${hazard.status}`,
                }))}
              />
              {(events.data ?? []).length === 0 ? (
                <p className="text-xs text-[var(--sev-2-fg)]">{t('noHazardEvents')}</p>
              ) : null}

              {/* Selection by division, DS division or district, with the codes still
                  editable as text. One list, edited from either side: two representations
                  of an area are two chances for them to disagree, and the one that
                  disagrees is the one that gets sent. */}
              <AreaSelector codes={divisions} onChange={setDivisions} />

              {/* Whether this message will wake people tonight, shown while it is still
                  being written. Discovering it from the delivery panel the next morning is
                  discovering it too late to reword or re-time. */}
              <QuietHoursNotice
                state={quietHoursState(new Date(), impactClassOf(selected))}
                locale={locale}
              />

              {failure ? <ErrorPanel error={failure} /> : null}

              {drafted ? (
                // The draft exists and is not sent. The next step is a separate screen
                // behind a mandatory dry run, which is the whole reason drafting and
                // sending are two calls.
                <div role="status" className="flex flex-wrap items-center gap-3">
                  <p className="text-sm text-[var(--verified)]">
                    {t('drafted', { reference: drafted.cap_identifier })}
                  </p>
                  <Button asChild variant="primary" size="sm">
                    <Link href={`/ops/alerts/${drafted.id}`}>{t('openDraft')}</Link>
                  </Button>
                </div>
              ) : null}

              {/* The send path is not on this screen. Drafting produces an alert that then
                  goes through sign-off and a mandatory dry run — see the note below. */}
              <section className="flex flex-col gap-2 rounded-[var(--radius-default)] border border-[var(--sev-2-border)] bg-[var(--sev-2-bg)] px-4 py-3 text-[var(--sev-2-fg)]">
                <p className="text-sm font-medium">{t('dryRunRequired')}</p>
                <p className="text-xs opacity-90">{t('dryRunExplanation')}</p>
              </section>

              <Button
                variant="primary"
                size="lg"
                // Over the segment limit in any language stops the draft here. The check
                // is a release gate on templates and it is the same gate on an instance:
                // a three-segment Tamil message is the community that gets it last.
                disabled={
                  overLimit || divisions.length === 0 || hazardEventId === '' || busy
                }
                busy={busy}
                busyLabel={t('draft')}
                onClick={draft}
                className="self-start"
              >
                {t('draft')}
              </Button>
              {overLimit ? (
                <p className="text-xs text-[var(--sev-3-fg)]">{t('overLimitBlocks')}</p>
              ) : null}
            </>
          ) : (
            <EmptyState title={t('pickTemplate')} description={t('templateHint')} />
          )}
        </>
      )}

      <p className="text-2xs text-[var(--text-muted)]">{alerts('noDenominator')}</p>
      <p className="text-2xs text-[var(--text-muted)]">{common('review')}</p>
    </div>
  );
}

/**
 * The three renderings, side by side, each with what it costs on the wire.
 *
 * Side by side rather than tabbed. A Sinhala message that runs to three segments is
 * invisible behind a tab, and the whole reason this panel exists is that the author is the
 * only person who can fix it and only while they are still writing.
 */
function Preview({ previews }: { readonly previews: Record<Locale, string> | null }) {
  const t = useTranslations('compose');
  if (!previews) return null;

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium">{t('preview')}</h2>
      <div className="grid gap-3 lg:grid-cols-3">
        {LOCALES.map((locale) => {
          const text = previews[locale];
          const count = countSegments(text);
          return (
            <article
              key={locale}
              lang={LANG_TAGS[locale]}
              data-preview-locale={locale}
              data-segments={count.segments}
              className={cn(
                'flex flex-col gap-2 rounded-[var(--radius-default)] border p-3',
                count.withinLimit
                  ? 'border-[var(--divider)] bg-[var(--surface-card)]'
                  : 'border-[var(--sev-3-border)] bg-[var(--sev-3-bg)] text-[var(--sev-3-fg)]',
              )}
            >
              <h3 className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
                {LOCALE_NAMES[locale]}
              </h3>
              <p className="text-sm leading-relaxed">{text}</p>
              <p data-sarana-datum="" className="font-mono text-2xs">
                {/* Segments, units and headroom — not a character count. Characters are
                    not what the gateway charges for or splits on. */}
                {t('segments', {
                  segments: count.segments,
                  max: MAX_SEGMENTS,
                  encoding: count.encoding,
                  headroom: count.headroom,
                })}
              </p>
            </article>
          );
        })}
      </div>
    </section>
  );
}
