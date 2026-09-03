/**
 * Class name composition.
 *
 * `tailwind-merge` on top of `clsx` so a caller's `className` wins over a component's
 * default without the component having to know which utilities it might be overriding.
 * Without it, `<Button className="bg-transparent">` emits two background utilities and
 * the winner depends on stylesheet order, which is a bug that only appears in production
 * builds.
 */

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
