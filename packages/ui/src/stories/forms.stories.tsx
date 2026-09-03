/**
 * Forms.
 *
 * `TrilingualField` is the one to look at. All three scripts are on screen at once rather
 * than behind tabs, because a tabbed trilingual field is how a record gets saved with two
 * languages filled in - the third tab is out of sight, the form submits, and the
 * completeness check becomes the only thing between that record and a citizen who cannot
 * read it.
 */

import type { Meta, StoryObj } from '@storybook/react-vite';
import { useState } from 'react';

import { OfflineSubmit, TrilingualField } from '../forms/index.js';
import { SpineNavButton } from '../domain/index.js';
import type { LocalisedText } from '@sarana/ts-shared/i18n';
import { LONGEST_LABELS, UI_STRINGS, pick } from './fixtures.js';
import { OnDark } from './trilingual.js';

const meta = { title: 'Forms', parameters: { layout: 'padded' } } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

function TrilingualFieldHarness({ seeded }: { readonly seeded: boolean }) {
  const [value, setValue] = useState<Partial<LocalisedText>>(
    seeded
      ? { en: 'Evacuate to Pallekele school', si: 'පල්ලේකැලේ පාසලට ඉවත් වන්න' }
      : {},
  );

  return (
    <TrilingualField
      label={pick(LONGEST_LABELS.emptyTitle!, 'en')}
      description={pick(LONGEST_LABELS.emptyDescription!, 'en')}
      value={value}
      onChange={setValue}
      completeLabel={pick(LONGEST_LABELS.translationComplete!, 'en')}
      incompleteLabel={(missing) =>
        `${pick(LONGEST_LABELS.translationIncomplete!, 'en')}: ${missing}`
      }
    />
  );
}

/** Two of three filled. The gap is visible on screen, not hidden behind a tab. */
export const TrilingualIncomplete: Story = {
  render: () => (
    <OnDark>
      <div className="max-w-md">
        <TrilingualFieldHarness seeded />
      </div>
    </OnDark>
  ),
};

export const TrilingualEmpty: Story = {
  render: () => (
    <OnDark>
      <div className="max-w-md">
        <TrilingualFieldHarness seeded={false} />
      </div>
    </OnDark>
  ),
};

export const Submits: Story = {
  render: () => (
    <OnDark>
      <div className="flex max-w-md flex-col gap-6">
        <OfflineSubmit
          online
          submitting={false}
          submitLabel={pick(LONGEST_LABELS.buttonPrimary!, 'en')}
          queueLabel="Save and send when online"
          queueExplanation="Held on this device until a signal is available."
        />
        {/* Offline: the button says the write will be queued, rather than saying
            "Submit" and succeeding silently into a local store. */}
        <OfflineSubmit
          online={false}
          submitting={false}
          submitLabel={pick(LONGEST_LABELS.buttonPrimary!, 'en')}
          queueLabel="Save and send when online"
          queueExplanation="Held on this device until a signal is available. Nothing is lost."
        />
        <OfflineSubmit
          online
          submitting
          submitLabel={pick(LONGEST_LABELS.buttonPrimary!, 'en')}
          queueLabel="Save and send when online"
          queueExplanation=""
        />
      </div>
    </OnDark>
  ),
};

export const SpineControls: Story = {
  render: () => (
    <OnDark>
      <div className="flex gap-2">
        <SpineNavButton onClick={() => undefined} label={pick(UI_STRINGS.previous!, 'en')}>
          {pick(UI_STRINGS.previous!, 'en')}
        </SpineNavButton>
        <SpineNavButton onClick={() => undefined} label={pick(UI_STRINGS.next!, 'en')}>
          {pick(UI_STRINGS.next!, 'en')}
        </SpineNavButton>
      </div>
    </OnDark>
  ),
};
