/**
 * The login route opts out of the console shell.
 *
 * A nested layout that renders only its children replaces the shell for this subtree,
 * which is how the sign-in page avoids the navigation and the gate banner without the
 * shell needing to know about routes.
 */

import type { ReactNode } from 'react';

export default function LoginLayout({ children }: { readonly children: ReactNode }) {
  return children;
}
