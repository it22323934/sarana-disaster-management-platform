import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import './globals.css';

export const metadata: Metadata = {
  title: 'SARANA Transparency Dashboard',
  description:
    'Public, independently verifiable view of disaster aid in Sri Lanka. Aggregate figures only.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
