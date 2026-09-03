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

const config: NextConfig = {
  reactStrictMode: true,
  // ADR-010: the apps run on ECS Fargate behind an ALB and serve their own static
  // assets. There is no CDN in front of them, and no bucket-only static site.
  output: 'standalone',
  // Workspace packages ship TypeScript source, not a build artefact.
  transpilePackages: ['@sarana/ui', '@sarana/ts-shared'],
  /**
   * Resolve the `.js` specifiers that TypeScript's ESM output convention requires.
   *
   * `@sarana/ui` and `@sarana/ts-shared` are `"type": "module"` and import each other as
   * `./tokens/index.js` while the file on disk is `index.ts` - which is what TypeScript
   * mandates for ESM and what `tsc` and Vite both understand. Webpack does not, so
   * without this every cross-file import inside the design system fails to resolve.
   * Turbopack handles it natively, so `next dev --turbo` works either way and only the
   * production build breaks - which is the worst place to find out.
   */
  webpack: (webpackConfig) => {
    webpackConfig.resolve.extensionAlias = {
      '.js': ['.ts', '.tsx', '.js'],
      '.jsx': ['.tsx', '.jsx'],
    };
    return webpackConfig;
  },
  env: {
    NEXT_PUBLIC_SARANA_API_URL: process.env.NEXT_PUBLIC_SARANA_API_URL,
    NEXT_PUBLIC_SARANA_ENV: process.env.NEXT_PUBLIC_SARANA_ENV,
  },
};

export default withNextIntl(config);
