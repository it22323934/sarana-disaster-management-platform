'use client';

/**
 * The client-side providers every console page sits inside.
 *
 * The retry policy is the part worth reading. TanStack's default retries any failure
 * three times, which is wrong here in both directions: a 403 will never succeed on retry
 * and retrying it delays the "you do not have access" message by seconds, while a 502
 * during a cyclone is worth retrying because the service may be restarting. So the
 * policy branches on what the failure was.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SaranaApiError } from '@sarana/ts-shared/schemas';
import { TooltipProvider } from '@sarana/ui';
import { useState, type ReactNode } from 'react';

/** Statuses where another attempt cannot change the answer. */
const TERMINAL_STATUSES = new Set([400, 401, 403, 404, 409, 422]);

function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof SaranaApiError && TERMINAL_STATUSES.has(error.problem.status)) {
    return false;
  }
  return failureCount < 3;
}

export function Providers({ children }: { readonly children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: shouldRetry,
            // Ten seconds. Long enough that navigating between panels does not refetch
            // everything, short enough that a queue reopened after a minute is refreshed.
            staleTime: 10_000,
            refetchOnWindowFocus: true,
          },
          mutations: {
            // A mutation on this console approves a dispatch or releases money. Retrying
            // one automatically is never right, even when it is idempotent: the operator
            // has to see what happened and decide again.
            retry: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  );
}
