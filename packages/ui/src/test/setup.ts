/**
 * jsdom gaps that the component library actually depends on.
 *
 * Everything stubbed here is something jsdom does not implement and Radix calls
 * unconditionally. Nothing here changes behaviour under test - if a stub starts
 * deciding an assertion, that assertion is testing the stub.
 */

import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
});

// Used by the reduced-motion branch and by every responsive component. jsdom has no
// layout, so the honest default is "no media query matches" - components must render
// their base case first and enhance from there, which is what we want anyway.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
}

// Radix's Select and Popover call these during open/close. jsdom implements neither.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => undefined;
  Element.prototype.releasePointerCapture = () => undefined;
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => undefined;
}

// The virtualised DataTable measures its viewport. jsdom reports every box as 0x0, so
// tests that care about virtualisation set explicit sizes; this keeps the rest from
// throwing.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
}
