/**
 * PostCSS for Storybook.
 *
 * Vite picks this up automatically, which is how Tailwind v4 gets compiled for the
 * component preview. The two Next.js apps carry their own identical config; this one
 * exists so the library can be previewed without either app running.
 */
const config = {
  plugins: {
    '@tailwindcss/postcss': {},
  },
};

export default config;
