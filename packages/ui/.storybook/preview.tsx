/**
 * Global decorators.
 *
 * Every story renders inside a themed surface, because a component in this system is not
 * meaningful without one: the severity chips, the focus ring and half the text colours
 * resolve per surface, and a story on a white Storybook canvas would show the light
 * variants of components whose home is a dark console.
 *
 * The theme toolbar switches the whole canvas rather than a wrapper, so the
 * `prefers-color-scheme` fallback in `tokens.css` is exercised too.
 */

import type { Decorator, Preview } from '@storybook/react-vite';
import { useEffect } from 'react';

import './preview.css';

const withTheme: Decorator = (Story, context) => {
  const theme = (context.globals['theme'] as string) ?? 'dark';

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.body.style.background = 'var(--surface-base)';
    document.body.style.color = 'var(--text-primary)';
    document.body.style.fontFamily = 'var(--font-sans)';
  }, [theme]);

  return <Story />;
};

const preview: Preview = {
  decorators: [withTheme],
  globalTypes: {
    theme: {
      description: 'Surface. The console is dark by default; the dashboard is light.',
      defaultValue: 'dark',
      toolbar: {
        title: 'Surface',
        icon: 'contrast',
        items: [
          { value: 'dark', title: 'Ops console (dark)' },
          { value: 'light', title: 'Public dashboard (light)' },
        ],
        dynamicTitle: true,
      },
    },
  },
  parameters: {
    controls: { expanded: true },
    a11y: {
      // Matches the CI sweep: colour is gated by test:contrast, which measures every
      // token pairing rather than only what is on screen.
      config: { rules: [{ id: 'color-contrast', enabled: false }] },
    },
  },
};

export default preview;
