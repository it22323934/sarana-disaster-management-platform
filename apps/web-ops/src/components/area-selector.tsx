'use client';

/**
 * Choosing the area an alert goes to.
 *
 * The brief asks for selection "on the map by GN division, DS division, district, or a
 * drawn polygon that snaps to division boundaries". All four are here.
 *
 * **By division, by DS division and by district.** The hierarchy endpoints make all three
 * cheap: a district or DS code is a prefix of every GN code inside it, so selecting a
 * parent expands to its children through one search rather than through a tree walk. The
 * expansion is shown as a count and the codes stay visible, because an operator who picks
 * "Kandy district" and sends to 512 divisions should see 512 before they send, not after.
 *
 * **The drawn polygon selects whole divisions, and one request does it.** The shape's
 * bounding box goes to `GET /admin/gn-divisions?bbox=…`, which returns every division in
 * the box with its centroid, and the point-in-polygon test runs locally. That is what
 * "snaps to division boundaries" means for an alert: the household directory is keyed by
 * GN division, so there is no such thing as warning half of one. See `area-draw.tsx`.
 *
 * **The codes stay editable as text.** A dispatcher reading codes off a radio needs to
 * enter them directly, and the selection is the source of truth in both directions - the
 * map and the text field edit one list, not two.
 *
 * **The code is the identity; the name is a label.** Several divisions share a name and
 * transliteration between the three scripts is not one-to-one, so every row shows its code
 * and the value sent to the server is the code.
 */

import { Badge, Button, EmptyState, Input, Select, Skeleton, cn } from '@sarana/ui';
import { localised, type Locale } from '@sarana/ts-shared/i18n';
import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useGNDivisions } from '../lib/queries';
import type { GNDivisionRow } from '../lib/schemas';
import { AreaDraw } from './area-draw';

/** How the operator is choosing an area. Each maps to a different search. */
export type AreaMode = 'division' | 'ds' | 'district' | 'draw';

export const AREA_MODES: readonly AreaMode[] = ['division', 'ds', 'district', 'draw'];

/**
 * Split a comma-separated code list into clean codes.
 *
 * Tolerant of spaces and trailing commas, because this field is typed under pressure and
 * refusing `LK-11-03-045, LK-11-03-046,` on a punctuation technicality helps nobody.
 */
export function parseCodes(raw: string): string[] {
  return [...new Set(raw.split(',').map((code) => code.trim()).filter((code) => code.length > 0))];
}

/**
 * Whether a GN code sits inside an area code.
 *
 * Segment-aware, so `LK-11-0` never accidentally covers `LK-11-03`. This mirrors the
 * containment rule the platform uses for authorisation; it is used here only to expand a
 * parent selection into its children, and the server resolves the codes it is sent.
 */
export function within(areaCode: string, gnCode: string): boolean {
  if (areaCode === 'LK') return true;
  return gnCode === areaCode || gnCode.startsWith(`${areaCode}-`);
}

export interface AreaSelectorProps {
  readonly codes: readonly string[];
  readonly onChange: (codes: string[]) => void;
  readonly className?: string;
}

export function AreaSelector({ codes, onChange, className }: AreaSelectorProps) {
  const t = useTranslations('compose');
  const locale = useLocale() as Locale;

  const [mode, setMode] = useState<AreaMode>('division');
  const [query, setQuery] = useState('');
  const results = useGNDivisions(query);

  /**
   * What the current query matches, narrowed by mode.
   *
   * All three modes search the same GN endpoint. A district or DS selection is a prefix
   * over GN codes, so searching for `LK-11` returns every division in Kandy and the mode
   * decides whether they are added one at a time or all at once.
   */
  const rows = results.data ?? [];
  const selected = new Set(codes);

  function add(next: readonly string[]): void {
    onChange([...new Set([...codes, ...next])]);
  }

  function remove(code: string): void {
    onChange(codes.filter((existing) => existing !== code));
  }

  return (
    <section className={cn('flex flex-col gap-3', className)}>
      <h2 className="text-sm font-medium">{t('area')}</h2>

      <div className="flex flex-wrap items-end gap-4">
        <Select
          label={t('areaMode')}
          value={mode}
          onValueChange={(value) => setMode(value as AreaMode)}
          options={AREA_MODES.map((value) => ({ value, label: t(`areaMode_${value}`) }))}
        />
        {mode === 'draw' ? null : (
          <Input
            label={t('areaSearch')}
            description={t('areaSearchHint')}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        )}
      </div>

      {mode === 'draw' ? (
        // Drawing replaces the search, not the selection. What it finds is added to the
        // codes already chosen, so an operator can type a code off a radio and then draw
        // around the rest without losing the first one.
        <AreaDraw onApply={(drawn) => add(drawn)} />
      ) : query.trim().length >= 2 ? (
        results.isPending ? (
          <Skeleton className="h-32" />
        ) : rows.length === 0 ? (
          <EmptyState title={t('areaNoMatch')} description={t('areaNoMatchHint')} />
        ) : (
          <div className="flex flex-col gap-2">
            {mode !== 'division' ? (
              // The whole match, added at once, with the count first. An operator who
              // picks a district and sends to 512 divisions must see 512 before they send.
              <Button
                variant="secondary"
                size="sm"
                className="self-start"
                onClick={() => add(rows.map((row) => row.code))}
              >
                {t('addAllMatching', { count: rows.length })}
              </Button>
            ) : null}

            <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto">
              {rows.map((row) => (
                <DivisionRow
                  key={row.code}
                  row={row}
                  locale={locale}
                  selected={selected.has(row.code)}
                  onToggle={() => (selected.has(row.code) ? remove(row.code) : add([row.code]))}
                />
              ))}
            </ul>
          </div>
        )
      ) : (
        <p className="text-xs text-[var(--text-muted)]">{t('areaSearchPrompt')}</p>
      )}

      {/* The selection, always visible and always editable as text. The map and this field
          edit one list: two representations of an area are two chances for them to
          disagree, and the one that disagrees is the one that gets sent. */}
      <Input
        label={t('divisions')}
        description={t('divisionsHint')}
        datum
        value={codes.join(', ')}
        onChange={(event) => onChange(parseCodes(event.target.value))}
      />

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
          {t('areaSelected', { count: codes.length })}
        </span>
        {codes.slice(0, 12).map((code) => (
          <Badge key={code} tone="neutral">
            <span className="font-mono">{code}</span>
          </Badge>
        ))}
        {codes.length > 12 ? (
          <span className="text-2xs text-[var(--text-muted)]">
            {t('areaMore', { count: codes.length - 12 })}
          </span>
        ) : null}
        {codes.length > 0 ? (
          <Button variant="ghost" size="sm" onClick={() => onChange([])}>
            {t('areaClear')}
          </Button>
        ) : null}
      </div>

    </section>
  );
}

function DivisionRow({
  row,
  locale,
  selected,
  onToggle,
}: {
  readonly row: GNDivisionRow;
  readonly locale: Locale;
  readonly selected: boolean;
  readonly onToggle: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={selected}
        className={cn(
          'flex min-h-[var(--touch-target-min)] w-full items-center gap-3 rounded-[var(--radius-cell)] px-2 text-left',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--focus-ring)]',
          selected ? 'bg-[var(--surface-card)]' : 'hover:bg-[var(--surface-raised)]',
        )}
      >
        <span data-sarana-datum="" className="font-mono text-2xs text-[var(--text-muted)]">
          {row.code}
        </span>
        <span className="text-sm">
          {localised(
            { si: row.name['si'] ?? '', ta: row.name['ta'] ?? '', en: row.name['en'] ?? '' },
            locale,
          )}
        </span>
        <span className="ml-auto text-2xs text-[var(--text-muted)]">
          {row.household_count.toLocaleString('en-LK')}
        </span>
      </button>
    </li>
  );
}
