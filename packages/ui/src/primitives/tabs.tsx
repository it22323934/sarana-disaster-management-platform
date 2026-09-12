'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * Tabs.
 *
 * The active tab is marked by a rule and a weight change, not by colour alone - the same
 * rule the severity ramp follows, for the same reason. A teal label against a slate one
 * is a hue difference and nothing else to a reader with a colour vision deficiency.
 */

import * as TabsPrimitive from '@radix-ui/react-tabs';
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';

export const Tabs = TabsPrimitive.Root;

export const TabsList = forwardRef<
  ElementRef<typeof TabsPrimitive.List>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(function TabsList({ className, ...rest }, ref) {
  return (
    <TabsPrimitive.List
      ref={ref}
      className={cn(
        'flex items-stretch gap-1 border-b border-[var(--divider)]',
        // Horizontal scroll rather than wrap: a wrapped tab strip moves the content
        // below it when a Tamil label pushes onto a second line.
        'overflow-x-auto',
        className,
      )}
      {...rest}
    />
  );
});

export const TabsTrigger = forwardRef<
  ElementRef<typeof TabsPrimitive.Trigger>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(function TabsTrigger({ className, ...rest }, ref) {
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        'relative min-h-[var(--touch-target-min)] whitespace-nowrap px-4 py-2',
        'text-sm text-[var(--text-muted)] transition-colors duration-[var(--motion-state)]',
        // The rule is the primary signal; the colour and weight reinforce it.
        'border-b-2 border-transparent',
        'data-[state=active]:border-[var(--text-accent)]',
        'data-[state=active]:font-medium data-[state=active]:text-[var(--text-primary)]',
        'disabled:cursor-not-allowed disabled:opacity-50',
        FOCUS_RING,
        className,
      )}
      {...rest}
    />
  );
});

export const TabsContent = forwardRef<
  ElementRef<typeof TabsPrimitive.Content>,
  ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(function TabsContent({ className, ...rest }, ref) {
  return (
    <TabsPrimitive.Content
      ref={ref}
      className={cn('pt-4 outline-none', FOCUS_RING, className)}
      {...rest}
    />
  );
});
