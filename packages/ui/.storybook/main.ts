/**
 * Storybook configuration.
 *
 * The a11y addon is here so a reviewer sees violations while looking at a component, but
 * it is not the gate - `pnpm test:a11y` runs axe over the same catalogue in CI and is
 * what actually blocks a merge. An addon panel nobody opens is not a check.
 */

import type { StorybookConfig } from '@storybook/react-vite';

const config: StorybookConfig = {
  stories: ['../src/**/*.stories.tsx'],
  addons: ['@storybook/addon-docs', '@storybook/addon-a11y'],
  framework: {
    name: '@storybook/react-vite',
    options: {},
  },
  // The library is consumed as source by both apps, so the preview compiles the same
  // files they do rather than a built bundle that could drift from them.
  typescript: { reactDocgen: 'react-docgen-typescript' },
};

export default config;
