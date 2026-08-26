import type { NextConfig } from 'next';

const config: NextConfig = {
  reactStrictMode: true,
  // ADR-010: the apps run on ECS Fargate behind an ALB and serve their own static
  // assets. There is no CDN in front of them, and no bucket-only static site.
  output: 'standalone',
  // Workspace packages ship TypeScript source, not a build artefact.
  transpilePackages: ['@sarana/ui', '@sarana/ts-shared'],
  env: {
    NEXT_PUBLIC_SARANA_API_URL: process.env.NEXT_PUBLIC_SARANA_API_URL,
    NEXT_PUBLIC_SARANA_ENV: process.env.NEXT_PUBLIC_SARANA_ENV,
    NEXT_PUBLIC_SARANA_MAP_STYLE_URL: process.env.NEXT_PUBLIC_SARANA_MAP_STYLE_URL,
  },
};

export default config;
