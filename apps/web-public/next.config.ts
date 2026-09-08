import createNextIntlPlugin from 'next-intl/plugin';
import type { NextConfig } from 'next';

/**
 * next-intl needs to be told where the per-request config lives.
 *
 * Without this the app compiles and then fails at request time with "Couldn't find
 * next-intl config file" on every route — a build that passes and a server that serves
 * nothing, which is the worst combination to discover late.
 */
const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');

/**
 * Whether to emit the standalone server bundle.
 *
 * ADR-010: the apps run on ECS Fargate behind an ALB and serve their own static assets.
 * There is no CloudFront in front of this one in Phase 1 — the trigger for adding it lives
 * in file 26's runbook — so the deployment artefact is a standalone bundle and this stays
 * the default.
 *
 * It is a flag for the same reason it is one in web-ops: the trace-copy step creates
 * symlinks, and Windows refuses them without Developer Mode, after compilation and every
 * static page have already succeeded. `pnpm build:local` sets it to 0, and that is what
 * the Playwright suite and any measurement against a served production build use.
 */
const STANDALONE = process.env['SARANA_BUILD_STANDALONE'] !== '0';

const config: NextConfig = {
  reactStrictMode: true,
  ...(STANDALONE ? { output: 'standalone' as const } : {}),
  // Workspace packages ship TypeScript source, not a build artefact.
  transpilePackages: ['@sarana/ui', '@sarana/ts-shared'],
  /**
   * Resolve the `.js` specifiers that TypeScript's ESM output convention requires.
   *
   * `@sarana/ui` and `@sarana/ts-shared` are `"type": "module"` and import each other as
   * `./tokens/index.js` while the file on disk is `index.ts` - which is what TypeScript
   * mandates for ESM and what `tsc` and Vite both understand. Webpack does not, so
   * without this every cross-file import inside the design system fails to resolve.
   */
  webpack: (webpackConfig) => {
    webpackConfig.resolve.extensionAlias = {
      '.js': ['.ts', '.tsx', '.js'],
      '.jsx': ['.tsx', '.jsx'],
    };
    return webpackConfig;
  },
  /**
   * No `env` block, and that is a decision rather than an omission.
   *
   * web-ops forwards `NEXT_PUBLIC_SARANA_API_URL` because its panels fetch from the
   * browser. Nothing on this app does: every figure is read server-side and rendered into
   * the HTML, because the brief requires the core numbers to work with JavaScript
   * disabled. Publishing a service URL to the browser would invite exactly the client-side
   * fetch that requirement rules out, and would put the internal topology of five services
   * into a page anyone can view-source.
   *
   * The one exception is the map style, which a browser genuinely has to load itself.
   */
  env: {
    NEXT_PUBLIC_SARANA_MAP_STYLE_URL: process.env.NEXT_PUBLIC_SARANA_MAP_STYLE_URL,
    NEXT_PUBLIC_SARANA_ENV: process.env.NEXT_PUBLIC_SARANA_ENV,
  },
};

export default withNextIntl(config);
