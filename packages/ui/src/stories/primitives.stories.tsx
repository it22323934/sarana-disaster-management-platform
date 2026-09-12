/**
 * Primitives, in three scripts.
 *
 * Every named export here is walked by `test:a11y`, so a component added to the library
 * without a story is a component axe never sees.
 */

import type { Meta, StoryObj } from '@storybook/react-vite';

import {
  Badge,
  Button,
  Checkbox,
  DialogContent,
  DialogRoot,
  DialogTrigger,
  Input,
  RadioGroup,
  Select,
  Skeleton,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  Toast,
  ToastProvider,
  ToastViewport,
  Tooltip,
  TooltipProvider,
} from '../primitives/index.js';
import { LONGEST_LABELS, UI_STRINGS, pick } from './fixtures.js';
import { OnDark, Trilingual } from './trilingual.js';

const meta = {
  title: 'Primitives',
  parameters: { layout: 'padded' },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const Buttons: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        render={(locale) => (
          <div className="flex flex-col gap-2">
            <Button variant="primary">{pick(LONGEST_LABELS.buttonPrimary!, locale)}</Button>
            <Button variant="secondary">{pick(UI_STRINGS.review!, locale)}</Button>
            <Button variant="ghost">{pick(UI_STRINGS.next!, locale)}</Button>
            {/* The only borrowed severity colour in the library, and only for actions
                that are themselves hazard-level. */}
            <Button variant="danger">{pick(UI_STRINGS.dismiss!, locale)}</Button>
            <Button variant="link">{pick(UI_STRINGS.verify!, locale)}</Button>
            <Button variant="primary" busy busyLabel={pick(UI_STRINGS.review!, locale)}>
              {pick(UI_STRINGS.review!, locale)}
            </Button>
            <Button variant="primary" disabled>
              {pick(UI_STRINGS.review!, locale)}
            </Button>
          </div>
        )}
      />
    </OnDark>
  ),
};

export const TextFields: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        render={(locale) => (
          <div className="flex flex-col gap-4">
            <Input
              label={pick(LONGEST_LABELS.adminLevel!, locale)}
              description={pick(LONGEST_LABELS.emptyDescription!, locale)}
              required
            />
            <Input
              label={pick(UI_STRINGS.searchDivision!, locale)}
              datum
              defaultValue="LK-11-03-045"
            />
            <Input
              label={pick(LONGEST_LABELS.statLabel!, locale)}
              error={pick(LONGEST_LABELS.translationIncomplete!, locale)}
            />
            <Textarea
              label={pick(LONGEST_LABELS.emptyTitle!, locale)}
              description={pick(LONGEST_LABELS.confidenceConsequence!, locale)}
            />
          </div>
        )}
      />
    </OnDark>
  ),
};

export const Toggles: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        render={(locale) => (
          <div className="flex flex-col gap-2">
            <Checkbox
              label={pick(LONGEST_LABELS.statLabel!, locale)}
              description={pick(LONGEST_LABELS.confidenceConsequence!, locale)}
            />
            <Switch
              label={pick(UI_STRINGS.enableSound!, locale)}
              description={pick(LONGEST_LABELS.offlineQueued!, locale)}
            />
            <RadioGroup
              legend={pick(LONGEST_LABELS.adminLevel!, locale)}
              defaultValue="a"
              options={[
                { value: 'a', label: pick(UI_STRINGS.online!, locale) },
                { value: 'b', label: pick(UI_STRINGS.offline!, locale) },
              ]}
            />
          </div>
        )}
      />
    </OnDark>
  ),
};

export const Selects: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        render={(locale) => (
          <Select
            label={pick(LONGEST_LABELS.adminLevel!, locale)}
            placeholder={pick(UI_STRINGS.searchDivision!, locale)}
            options={[
              { value: 'lk-11', label: pick(LONGEST_LABELS.adminLevel!, locale) },
              { value: 'lk-12', label: pick(LONGEST_LABELS.statLabel!, locale) },
            ]}
          />
        )}
      />
    </OnDark>
  ),
};

export const Badges: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        render={(locale) => (
          <div className="flex flex-wrap gap-2">
            <Badge tone="neutral">{pick(UI_STRINGS.online!, locale)}</Badge>
            <Badge tone="accent">{pick(UI_STRINGS.review!, locale)}</Badge>
            <Badge tone="verified">{pick(LONGEST_LABELS.translationComplete!, locale)}</Badge>
            <Badge tone="pending">{pick(UI_STRINGS.approvalHistory!, locale)}</Badge>
          </div>
        )}
      />
    </OnDark>
  ),
};

export const Skeletons: Story = {
  render: () => (
    <OnDark>
      <div className="flex w-80 flex-col gap-2">
        <Skeleton line />
        <Skeleton line className="w-2/3" />
        <Skeleton className="h-24" />
      </div>
    </OnDark>
  ),
};

export const TabStrip: Story = {
  render: () => (
    <OnDark>
      <Trilingual
        width={420}
        render={(locale) => (
          <Tabs defaultValue="one">
            <TabsList>
              <TabsTrigger value="one">{pick(UI_STRINGS.incidentQueue!, locale)}</TabsTrigger>
              <TabsTrigger value="two">{pick(UI_STRINGS.approvalHistory!, locale)}</TabsTrigger>
            </TabsList>
            <TabsContent value="one">
              <p className="text-sm">{pick(LONGEST_LABELS.emptyDescription!, locale)}</p>
            </TabsContent>
            <TabsContent value="two">
              <p className="text-sm">{pick(LONGEST_LABELS.confidenceConsequence!, locale)}</p>
            </TabsContent>
          </Tabs>
        )}
      />
    </OnDark>
  ),
};

export const DialogAndTooltip: Story = {
  render: () => (
    <OnDark>
      <TooltipProvider>
        <Trilingual
          render={(locale) => (
            <div className="flex flex-col gap-2">
              <DialogRoot>
                <DialogTrigger asChild>
                  <Button variant="primary">{pick(UI_STRINGS.review!, locale)}</Button>
                </DialogTrigger>
                <DialogContent
                  title={pick(LONGEST_LABELS.gateTitle!, locale)}
                  description={pick(LONGEST_LABELS.emptyDescription!, locale)}
                >
                  <Button variant="primary">{pick(UI_STRINGS.review!, locale)}</Button>
                </DialogContent>
              </DialogRoot>

              {/* The tooltip repeats what is already visible beside it. It is never the
                  only place the information appears - see overlays.tsx. */}
              <Tooltip content={pick(LONGEST_LABELS.confidenceConsequence!, locale)}>
                <Button variant="ghost">{pick(LONGEST_LABELS.confidenceConsequence!, locale)}</Button>
              </Tooltip>
            </div>
          )}
        />
      </TooltipProvider>
    </OnDark>
  ),
};

export const Toasts: Story = {
  render: () => (
    <OnDark>
      <ToastProvider>
        <div className="flex flex-col gap-2">
          <Toast
            open
            tone="success"
            title={pick(LONGEST_LABELS.translationComplete!, 'en')}
            description={pick(LONGEST_LABELS.confidenceConsequence!, 'en')}
            closeLabel={pick(UI_STRINGS.dismiss!, 'en')}
          />
          <Toast
            open
            tone="error"
            title={pick(LONGEST_LABELS.translationIncomplete!, 'ta')}
            closeLabel={pick(UI_STRINGS.dismiss!, 'ta')}
          />
        </div>
        <ToastViewport />
      </ToastProvider>
    </OnDark>
  ),
};
