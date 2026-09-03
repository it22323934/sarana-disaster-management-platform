import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import './globals.css';

export const metadata: Metadata = {
  title: 'SARANA Transparency Dashboard',
  description:
    'Public, independently verifiable view of disaster aid in Sri Lanka. Aggregate figures only.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // The public dashboard is light by default: it is read in daylight, screenshotted into
  // articles, and printed. A reader can still switch; the default is the decision.
  //
  // `lang` is set per-request once locale negotiation lands with build file 21. English
  // is the documented default until then, matching the API.
  return (
    <html lang="en" data-theme="light">
      <body>{children}</body>
    </html>
  );
}
