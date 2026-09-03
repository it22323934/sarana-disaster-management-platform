/**
 * The two human gates, and the data surfaces.
 *
 * The gate stories render all three escalation states at once. That is deliberate: the
 * thresholds are the design, and seeing "waiting", "prominent" and "persistent" together
 * is the only way to judge whether the escalation is actually noticeable at 3am.
 */

import type { Meta, StoryObj } from '@storybook/react-vite';

import {
  DataTable,
  EmptyState,
  Pagination,
  StatCard,
  TrendSparkline,
} from '../data/index.js';
import { MockDataBadge, PendingGateBanner, SeverityPill } from '../domain/index.js';
import { MapLegend } from '../map/index.js';
import { Button } from '../primitives/index.js';
import { SEVERITY_LABELS } from '../tokens/severity.js';
import type { SeverityLevel } from '../tokens/severity.js';
import {
  LONGEST_LABELS,
  STORY_DIVISIONS,
  STORY_NOW,
  UI_STRINGS,
  pick,
} from './fixtures.js';
import { OnDark, OnLight, Trilingual } from './trilingual.js';

const meta = { title: 'Gates and data', parameters: { layout: 'padded' } } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

/** Ages chosen to land one state either side of each threshold. */
const GATE_AGES = [
  { id: 'waiting', since: '2025-11-27T22:59:20Z' },
  { id: 'prominent', since: '2025-11-27T22:56:30Z' },
  { id: 'persistent', since: '2025-11-27T22:52:00Z' },
];

export const GateEscalation: Story = {
  render: () => (
    <OnDark>
      <div className="flex flex-col gap-4">
        {GATE_AGES.map((age) => (
          <PendingGateBanner
            key={age.id}
            kind="dispatch"
            count={2}
            oldestWaitingSince={age.since}
            now={STORY_NOW}
            title={() => pick(LONGEST_LABELS.gateTitle!, 'en')}
            ageLabel={(seconds) => `Oldest waiting ${Math.round(seconds / 60)} min`}
            action={<Button variant="primary">{pick(UI_STRINGS.review!, 'en')}</Button>}
            onEnableSound={() => undefined}
            soundLabel={pick(UI_STRINGS.enableSound!, 'en')}
          />
        ))}
      </div>
    </OnDark>
  ),
};

export const GateTrilingual: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        width={420}
        render={(locale) => (
          <PendingGateBanner
            kind="disbursement"
            count={2}
            oldestWaitingSince="2025-11-27T22:52:00Z"
            now={STORY_NOW}
            title={() => pick(LONGEST_LABELS.gateTitle!, locale)}
            ageLabel={(seconds) => `${Math.round(seconds / 60)} min`}
            action={<Button variant="primary">{pick(UI_STRINGS.review!, locale)}</Button>}
          />
        )}
      />
    </OnDark>
  ),
};

export const Stats: Story = {
  render: () => (
    <OnLight>
      <Trilingual
        width={260}
        render={(locale) => (
          <StatCard
            label={pick(LONGEST_LABELS.statLabel!, locale)}
            value="1,203"
            context={pick(LONGEST_LABELS.confidenceConsequence!, locale)}
            asOf="28 Nov 2025, 04:30"
            footer={
              <div className="flex flex-wrap items-center gap-2">
                <TrendSparkline
                  points={[4, 9, 7, 14, 22, 19, 31]}
                  summary={pick(LONGEST_LABELS.statLabel!, locale)}
                />
                <MockDataBadge locale={locale} />
              </div>
            }
          />
        )}
      />
    </OnLight>
  ),
};

export const Empty: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        width={360}
        render={(locale) => (
          <EmptyState
            title={pick(LONGEST_LABELS.emptyTitle!, locale)}
            description={pick(LONGEST_LABELS.emptyDescription!, locale)}
            action={<Button variant="secondary">{pick(UI_STRINGS.dismiss!, locale)}</Button>}
          />
        )}
      />
    </OnDark>
  ),
};

export const Paging: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        width={380}
        render={(locale) => (
          <Pagination
            hasPrevious
            hasNext
            label={pick(UI_STRINGS.incidentQueue!, locale)}
            previousLabel={pick(UI_STRINGS.previous!, locale)}
            nextLabel={pick(UI_STRINGS.next!, locale)}
            summary="50 / 1,203"
          />
        )}
      />
    </OnDark>
  ),
};

interface QueueRow {
  readonly code: string;
  readonly division: string;
  readonly level: SeverityLevel;
}

const ROWS: readonly QueueRow[] = STORY_DIVISIONS.map((division, index) => ({
  code: `INC-251128-${String(index).padStart(6, '0')}`,
  division: division.name.en,
  level: ((index % 5) as SeverityLevel),
}));

export const Table: Story = {
  render: () => (
    <OnDark>
      <DataTable
        caption="Incident queue"
        height="20rem"
        rows={ROWS}
        rowKey={(row) => row.code}
        onRowActivate={() => undefined}
        columns={[
          {
            key: 'code',
            header: 'Reference',
            width: '14rem',
            cell: (row) => (
              <span data-sarana-datum="" className="font-mono text-xs">
                {row.code}
              </span>
            ),
          },
          { key: 'division', header: 'Division', cell: (row) => row.division },
          {
            key: 'severity',
            header: 'Severity',
            width: '10rem',
            cell: (row) => <SeverityPill level={row.level} locale="en" />,
          },
        ]}
      />
    </OnDark>
  ),
};

export const Legend: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        width={240}
        render={(locale) => (
          <MapLegend
            title={pick(UI_STRINGS.timeline!, locale)}
            levels={[2, 3, 4]}
            labels={{
              0: SEVERITY_LABELS[0][locale],
              1: SEVERITY_LABELS[1][locale],
              2: SEVERITY_LABELS[2][locale],
              3: SEVERITY_LABELS[3][locale],
              4: SEVERITY_LABELS[4][locale],
            }}
          />
        )}
      />
    </OnDark>
  ),
};
