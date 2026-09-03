import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import './globals.css';

export const metadata: Metadata = {
  title: 'SARANA Operations Console',
  description:
    'Operator, GN officer and approver console for the SARANA disaster response platform.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // `lang` is set per-request once locale negotiation lands with the console shell in
  // build file 20. English is the documented default until then, matching the API.
  //
  // Operations rooms run dark, and a mid-range Android in the field saves real battery
  // on an OLED panel. An operator can still switch; the default is the decision.
  return (
    <html lang="en" data-theme="dark">
      <body>{children}</body>
    </html>
  );
}
