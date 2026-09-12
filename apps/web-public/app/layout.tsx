/**
 * The root layout.
 *
 * Deliberately thin. Next requires a root layout with `<html>` and `<body>`, but the real
 * one is `app/[locale]/layout.tsx`, which is where the locale is known and where `lang`
 * and the font stacks can be set correctly. Setting `lang="en"` here and overriding it
 * below would ship a wrong `lang` to anything rendered outside the locale segment — and on
 * a trilingual public site that is the difference between a screen reader speaking Tamil
 * and a screen reader spelling it out in English phonemes.
 */

import type { ReactNode } from 'react';

import './globals.css';

export default function RootLayout({ children }: { readonly children: ReactNode }) {
  return children as ReactNode;
}
