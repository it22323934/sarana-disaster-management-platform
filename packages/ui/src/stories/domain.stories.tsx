/**
 * Domain components, in three scripts, on both surfaces.
 *
 * The severity stories render the full ramp on the dark console and the light dashboard,
 * because the chip variants are per-surface and a level that is legible on one and not
 * the other is exactly what the two-surface sweep is for.
 */

import type { Meta, StoryObj } from '@storybook/react-vite';
import type { SeverityLevel } from '../tokens/severity.js';

import {
  AuditTrail,
  ConfidenceMeter,
  GNDivisionPicker,
  HashDisplay,
  ImpactClassBadge,
  LKRAmount,
  LanguageSwitcher,
  LocalisedText,
  MockDataBadge,
  OfflineIndicator,
  ReferenceCode,
  RelativeTime,
  SeverityDot,
  SeverityPill,
  TimeSpine,
  TranslationCompleteness,
} from '../domain/index.js';
import { SEVERITY_LABELS, SEVERITY_LEVELS } from '../tokens/severity.js';
import {
  DIVISION_NAMES,
  LONGEST_LABELS,
  STORY_DIVISIONS,
  STORY_LANDFALL,
  STORY_NOW,
  UI_STRINGS,
  pick,
} from './fixtures.js';
import { OnDark, OnLight, Trilingual } from './trilingual.js';

const meta = { title: 'Domain', parameters: { layout: 'padded' } } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const SeverityRampOnDark: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        render={(locale) => (
          <div className="flex flex-col items-start gap-2">
            {SEVERITY_LEVELS.map((level) => (
              <SeverityPill key={level} level={level} locale={locale} />
            ))}
          </div>
        )}
      />
    </OnDark>
  ),
};

export const SeverityRampOnLight: Story = {
  render: () => (
    <OnLight>
      <Trilingual
        render={(locale) => (
          <div className="flex flex-col items-start gap-2">
            {SEVERITY_LEVELS.map((level) => (
              <SeverityPill key={level} level={level} locale={locale} />
            ))}
          </div>
        )}
      />
    </OnLight>
  ),
};

export const SeverityInMonochrome: Story = {
  // The point of the story: with the hue removed, the five levels are still separable,
  // because each carries a distinct silhouette and its own word.
  render: () => (
    <OnDark>
      <div style={{ filter: 'grayscale(1)' }}>
        <Trilingual
          render={(locale) => (
            <div className="flex flex-col items-start gap-2">
              {SEVERITY_LEVELS.map((level) => (
                <SeverityPill key={level} level={level} locale={locale} />
              ))}
            </div>
          )}
        />
      </div>
    </OnDark>
  ),
};

export const SeverityDots: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        render={(locale) => (
          <ul className="flex flex-col gap-2">
            {SEVERITY_LEVELS.map((level) => (
              <li key={level} className="flex items-center gap-2 text-sm">
                <SeverityDot level={level} label={SEVERITY_LABELS[level][locale]} />
                <span>{SEVERITY_LABELS[level][locale]}</span>
              </li>
            ))}
          </ul>
        )}
      />
    </OnDark>
  ),
};

export const ImpactClasses: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        render={(locale) => (
          <div className="flex flex-col items-start gap-2">
            {([2, 3, 4] as SeverityLevel[]).map((level) => (
              <ImpactClassBadge
                key={level}
                impactClass={level}
                locale={locale}
                prefix={pick(UI_STRINGS.predictedImpact!, locale)}
              />
            ))}
          </div>
        )}
      />
    </OnDark>
  ),
};

export const Data: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        width={380}
        render={(locale) => (
          <div className="flex flex-col gap-3">
            <LKRAmount cents={125_000_00} />
            <LKRAmount cents={25_000_00} voided voidedLabel={pick(UI_STRINGS.dismiss!, locale)} />
            <ReferenceCode code="INC-251128-K4M2XA" kind={pick(UI_STRINGS.incidentQueue!, locale)} />
            <RelativeTime value="2025-11-27T22:18:00Z" locale={locale} now={STORY_NOW} />
            <HashDisplay
              hash="9f2b1c4e7a5d3f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708"
              copyLabel={pick(UI_STRINGS.copy!, locale)}
              copiedLabel={pick(UI_STRINGS.copied!, locale)}
              verifyHref="#verify"
              verifyLabel={pick(UI_STRINGS.verify!, locale)}
            />
          </div>
        )}
      />
    </OnDark>
  ),
};

export const Trust: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        width={380}
        render={(locale) => (
          <div className="flex flex-col items-start gap-4">
            <MockDataBadge
              locale={locale}
              source={pick(LONGEST_LABELS.simulatedSource!, locale)}
            />
            <ConfidenceMeter
              value={0.62}
              band="medium"
              bandLabel={pick(UI_STRINGS.review!, locale)}
              consequence={pick(LONGEST_LABELS.confidenceConsequence!, locale)}
            />
            <OfflineIndicator
              online={false}
              queued={3}
              onlineLabel={pick(UI_STRINGS.online!, locale)}
              offlineLabel={pick(UI_STRINGS.offline!, locale)}
              queuedLabel={() => pick(LONGEST_LABELS.offlineQueued!, locale)}
            />
            <TranslationCompleteness
              present={['en', 'si']}
              completeLabel={pick(LONGEST_LABELS.translationComplete!, locale)}
              incompleteLabel={(missing) =>
                `${pick(LONGEST_LABELS.translationIncomplete!, locale)}: ${missing}`
              }
            />
          </div>
        )}
      />
    </OnDark>
  ),
};

export const Localisation: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        render={(locale) => (
          <div className="flex flex-col items-start gap-3">
            <LanguageSwitcher
              locale={locale}
              onChange={() => undefined}
              label={pick(UI_STRINGS.language!, locale)}
            />
            <LocalisedText value={DIVISION_NAMES[0]!} locale={locale} as="p" />
            <LocalisedText value={DIVISION_NAMES[3]!} locale={locale} as="p" />
          </div>
        )}
      />
    </OnDark>
  ),
};

export const DivisionPicker: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        width={380}
        render={(locale) => (
          <GNDivisionPicker
            divisions={STORY_DIVISIONS}
            value="LK-11-03-001"
            onChange={() => undefined}
            locale={locale}
            label={pick(UI_STRINGS.searchDivision!, locale)}
            resultsLabel={(count) => `${count}`}
          />
        )}
      />
    </OnDark>
  ),
};

export const Spine: Story = {
  render: () => (
    <OnDark>
      <TimeSpine
        landfall={STORY_LANDFALL}
        now="2025-11-28T06:00:00Z"
        label={pick(UI_STRINGS.timeline!, 'en')}
        nowLabel={pick(UI_STRINGS.youAreHere!, 'en')}
        milestones={[
          { id: 'forecast', at: '2025-11-25T00:00:00Z', label: 'Forecast issued' },
          { id: 'alert', at: '2025-11-27T12:00:00Z', label: 'Alerts dispatched' },
          { id: 'incident', at: '2025-11-28T02:00:00Z', label: 'First incident' },
          {
            id: 'disburse',
            at: '2025-12-05T00:00:00Z',
            label: 'First disbursement',
            projected: true,
          },
        ]}
      />
    </OnDark>
  ),
};

export const SpineCompact: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        width={360}
        render={(locale) => (
          <TimeSpine
            compact
            landfall={STORY_LANDFALL}
            now="2025-12-09T06:00:00Z"
            locale={locale}
            label={pick(UI_STRINGS.timeline!, locale)}
            nowLabel={pick(UI_STRINGS.youAreHere!, locale)}
            phaseLabel={pick(UI_STRINGS.recovery!, locale)}
          />
        )}
      />
    </OnDark>
  ),
};

export const Audit: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        width={380}
        render={(locale) => (
          <AuditTrail
            label={pick(UI_STRINGS.approvalHistory!, locale)}
            entries={[
              {
                id: '1',
                at: '28 Nov 2025, 04:30',
                actor: 'agent:triage',
                action: pick(LONGEST_LABELS.confidenceConsequence!, locale),
                correlationId: '018f3c2a-7b41-7e90-9c2d-5f6a7b8c9d0e',
              },
              {
                id: '2',
                at: '28 Nov 2025, 04:36',
                actor: 'role:dispatcher',
                action: pick(UI_STRINGS.review!, locale),
              },
            ]}
          />
        )}
      />
    </OnDark>
  ),
};
