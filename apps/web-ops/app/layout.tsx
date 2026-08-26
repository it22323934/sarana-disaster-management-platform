import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import './globals.css';

export const metadata: Metadata = {
  title: 'SARANA Operations Console',
  description:
    'Operator, GN officer and approver console for the SARANA disaster response platform.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // `lang` is set per-request once locale negotiation lands with the design system.
  // Until then English is the documented default, matching the API.
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
