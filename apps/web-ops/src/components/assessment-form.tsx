'use client';

/**
 * `/field/assessments/new` — the web fallback for the Field Companion.
 *
 * The Field Companion is the real tool: a GN officer assesses damage standing in front of
 * a house, with photographs carrying EXIF GPS, an offline queue and a capability token
 * issued before going into the field. This screen exists for the case the brief names it
 * for — the handset is dead, lost or was never issued — and it is built to be *worse* than
 * the mobile app in exactly the ways it actually is, visibly, rather than to feel
 * equivalent.
 *
 * **It files no evidence, and it says so before the button.** `evidence_photo_uris` and
 * `evidence_hash` go as null. A browser at a desk has no photograph of the house and no
 * EXIF GPS from it, and media signing is not wired in any case. An assessment filed here
 * is one nobody photographed, and the approver reading it at the money gate will see no
 * evidence — which is the correct thing for them to see.
 *
 * **It records no position, and it says what that costs.** `latitude`/`longitude` on an
 * assessment mean *where the officer stood*, and they exist so an assessment filed from
 * thirty kilometres away can be flagged. Sending the desk's coordinates would satisfy the
 * field and defeat the check; sending nothing means the check cannot run on this record,
 * and saying so is better than quietly passing it.
 *
 * **The household is chosen by reference, never by name.** `GET /admin/households` selects
 * no personal data at all, so there is nothing here to redact. An officer identifies the
 * household the way the platform does.
 *
 * **`assessed_by` comes from the token and is never in the body.** An officer cannot file
 * under somebody else's name, which is what makes the segregation check at release time —
 * the releaser is not the assessor — mean anything.
 *
 * **The idempotency key is generated once per form, not per click.** A double-tap replays
 * the stored record rather than creating a second assessment for the same household, which
 * is a duplicate entitlement and eventually a duplicate payment.
 */

import {
  Badge,
  Button,
  EmptyState,
  Input,
  ReferenceCode,
  Select,
  Skeleton,
  cn,
} from '@sarana/ui';
import { localised, type Locale } from '@sarana/ts-shared/i18n';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

import { Link } from '../i18n/routing';
import { gatewayFetch } from '../lib/gateway-client';
import { useGNDivisions, useHazardEvents, useHouseholds } from '../lib/queries';
import { DAMAGE_CATEGORIES, createdAssessmentSchema } from '../lib/schemas';
import { ErrorPanel } from './degraded';

export function AssessmentForm() {
  const t = useTranslations('assessments');
  const cop = useTranslations('cop');
  const compose = useTranslations('compose');
  const locale = useLocale() as Locale;

  const [divisionQuery, setDivisionQuery] = useState('');
  const [divisionId, setDivisionId] = useState('');
  const [divisionCode, setDivisionCode] = useState('');
  const [householdId, setHouseholdId] = useState('');
  const [hazardEventId, setHazardEventId] = useState('');
  const [category, setCategory] = useState('');
  const [subcategory, setSubcategory] = useState('');
  const [rupees, setRupees] = useState('');
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ public_ref: string; duplicate: boolean } | null>(null);
  const [failure, setFailure] = useState<unknown>(null);

  const divisions = useGNDivisions(divisionQuery);
  const households = useHouseholds(divisionId);
  const events = useHazardEvents();

  /**
   * One key per form instance.
   *
   * Generated when the component mounts and reused for every attempt, so a retry after a
   * network failure replays the stored record. Regenerating per click would let a
   * double-tap file two assessments for one household - two entitlements, and eventually
   * two payments.
   */
  const operationId = useMemo(() => `web-${crypto.randomUUID()}`, []);

  const cents = Math.round(Number(rupees.replace(/[^\d.]/g, '')) * 100);
  const amountValid = Number.isFinite(cents) && cents >= 0 && rupees.trim().length > 0;
  const complete =
    divisionId !== '' && householdId !== '' && hazardEventId !== '' && category !== '' && amountValid;

  async function submit(): Promise<void> {
    setBusy(true);
    setFailure(null);
    try {
      const record = await gatewayFetch('assessments', {
        method: 'POST',
        body: {
          household_id: householdId,
          gn_division_id: divisionId,
          gn_division_code: divisionCode,
          hazard_event_id: hazardEventId,
          category,
          subcategory: subcategory.trim(),
          cost_estimate_lkr_cents: cents,
          assessed_at: new Date().toISOString(),
          // Null, deliberately, and the screen says so above the button. See the module
          // docstring: there is no photograph and no field position from a desk, and
          // sending a desk position would defeat the distance check rather than satisfy it.
          evidence_photo_uris: null,
          evidence_hash: null,
          latitude: null,
          longitude: null,
          gps_accuracy_m: null,
          client_operation_id: operationId,
        },
        idempotencyKey: operationId,
        schema: createdAssessmentSchema,
      });
      setCreated({ public_ref: record.public_ref, duplicate: record.duplicate });
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <EmptyState
          title={created.duplicate ? t('alreadyFiled') : t('filed')}
          description={created.duplicate ? t('alreadyFiledHint') : t('filedHint')}
          action={
            <div className="flex flex-wrap items-center gap-3">
              <ReferenceCode code={created.public_ref} />
              <Button asChild variant="secondary">
                <Link href="/field/assessments">{t('title')}</Link>
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold">{t('newTitle')}</h1>
        <p className="text-sm text-[var(--text-muted)]">{t('newSubtitle')}</p>
      </header>

      {/* Before the form, not after it. An officer should decide whether to use this
          screen knowing what it cannot do, rather than discover it at the submit button. */}
      <section
        className={cn(
          'flex flex-col gap-2 rounded-[var(--radius-default)] border px-4 py-3',
          'border-[var(--sev-2-border)] bg-[var(--sev-2-bg)] text-[var(--sev-2-fg)]',
        )}
      >
        <h2 className="text-sm font-medium">{t('deskFiledTitle')}</h2>
        <ul className="ml-4 list-disc text-xs">
          <li>{t('deskFiledNoPhotos')}</li>
          <li>{t('deskFiledNoPosition')}</li>
          <li>{t('deskFiledUseApp')}</li>
        </ul>
      </section>

      <Input
        label={compose('areaSearch')}
        description={compose('areaSearchHint')}
        value={divisionQuery}
        onChange={(event) => setDivisionQuery(event.target.value)}
      />

      {divisionQuery.trim().length >= 2 ? (
        divisions.isPending ? (
          <Skeleton className="h-24" />
        ) : (
          <Select
            label={cop('division')}
            placeholder={compose('areaSearchPrompt')}
            value={divisionId}
            onValueChange={(value) => {
              setDivisionId(value);
              setDivisionCode(
                (divisions.data ?? []).find((division) => division.id === value)?.code ?? '',
              );
              // The household belonged to the previous division. Keeping it would file an
              // assessment for a household in a division the officer just changed away
              // from, which the service would accept.
              setHouseholdId('');
            }}
            options={(divisions.data ?? []).map((division) => ({
              value: division.id,
              label: `${division.code} · ${localised(
                {
                  si: division.name['si'] ?? '',
                  ta: division.name['ta'] ?? '',
                  en: division.name['en'] ?? '',
                },
                locale,
              )}`,
            }))}
          />
        )
      ) : null}

      {divisionId ? (
        households.isPending ? (
          <Skeleton className="h-24" />
        ) : (households.data ?? []).length === 0 ? (
          <p className="text-xs text-[var(--text-muted)]">{t('noHouseholds')}</p>
        ) : (
          <Select
            label={t('household')}
            description={t('householdHint')}
            value={householdId}
            onValueChange={setHouseholdId}
            // The reference code and the composition, which is all the platform holds and
            // all an officer needs to identify the right house. No name exists to show.
            options={(households.data ?? []).map((household) => ({
              value: household.id,
              label: `${household.reference_code} · ${t('members', {
                count: household.member_count,
              })}`,
            }))}
          />
        )
      ) : null}

      <Select
        label={t('hazardEvent')}
        placeholder={compose('hazardEventHint')}
        value={hazardEventId}
        onValueChange={setHazardEventId}
        options={(events.data ?? []).map((event) => ({
          value: event.id,
          label: `${localised(event.name, locale)} · ${event.status}`,
        }))}
      />

      <Select
        label={t('category')}
        value={category}
        onValueChange={setCategory}
        options={DAMAGE_CATEGORIES.map((value) => ({ value, label: value }))}
      />

      <Input
        label={t('subcategory')}
        description={t('subcategoryHint')}
        value={subcategory}
        onChange={(event) => setSubcategory(event.target.value.slice(0, 48))}
      />

      <Input
        label={t('costEstimate')}
        description={t('costEstimateHint')}
        datum
        inputMode="decimal"
        value={rupees}
        onChange={(event) => setRupees(event.target.value)}
        error={rupees.trim().length > 0 && !amountValid ? t('costInvalid') : undefined}
      />

      {failure ? <ErrorPanel error={failure} /> : null}

      {/* The consequence, restated where the decision is made. */}
      <div className="flex flex-wrap items-center gap-3">
        <Badge tone="pending">{t('noEvidenceBadge')}</Badge>
        <Button
          variant="primary"
          size="lg"
          disabled={!complete || busy}
          busy={busy}
          busyLabel={t('fileAssessment')}
          onClick={submit}
        >
          {t('fileAssessment')}
        </Button>
      </div>
    </div>
  );
}
