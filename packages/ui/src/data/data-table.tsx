'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * DataTable. Virtualised, and still a real `<table>`.
 *
 * The virtualisation is what makes a 14,000-row GN division list usable on the mid-range
 * hardware an operations room actually has. The thing that is easy to get wrong is doing
 * it with nested divs and ARIA grid roles: screen reader support for `role="grid"` is
 * inconsistent, and an operator using one would lose row and column announcements on a
 * table they navigate all day. So the markup stays semantic and only the rows outside the
 * viewport are omitted - with `aria-rowcount` on the table and `aria-rowindex` on each
 * row, so assistive technology is told the real size and the real position rather than
 * "row 4 of 12" when there are nine thousand.
 */

import { useVirtualizer } from '@tanstack/react-virtual';
import { useRef, type ReactNode } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';

export interface Column<Row> {
  readonly key: string;
  readonly header: ReactNode;
  /** Rendered per row. Keep it cheap: it runs for every visible row on every scroll. */
  readonly cell: (row: Row) => ReactNode;
  /** Fixed track width, e.g. `12rem`. Omit for a flexible column. */
  readonly width?: string;
  /** Right-align. Use for every numeric column so digits line up down the track. */
  readonly numeric?: boolean;
}

export interface DataTableProps<Row> {
  readonly caption: string;
  readonly columns: readonly Column<Row>[];
  readonly rows: readonly Row[];
  readonly rowKey: (row: Row) => string;
  readonly onRowActivate?: (row: Row) => void;
  /** Shown in place of the body when `rows` is empty. Use `EmptyState`. */
  readonly empty?: ReactNode;
  /** Viewport height. The table scrolls inside it rather than growing the page. */
  readonly height?: string;
  readonly rowHeight?: number;
  readonly className?: string;
}

export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
  onRowActivate,
  empty,
  height = '32rem',
  rowHeight = 44,
  className,
}: DataTableProps<Row>) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    // Six rows of slack above and below. Enough that a fast scroll does not show blank
    // space, few enough that the DOM stays small on a low-end machine.
    overscan: 6,
  });

  if (rows.length === 0 && empty) {
    return (
      <div className={cn('rounded-[var(--radius-default)] border border-[var(--divider)]', className)}>
        {empty}
      </div>
    );
  }

  const items = virtualizer.getVirtualItems();
  const paddingTop = items[0]?.start ?? 0;
  const paddingBottom =
    items.length > 0 ? virtualizer.getTotalSize() - (items[items.length - 1]?.end ?? 0) : 0;

  return (
    <div
      ref={scrollRef}
      style={{ height }}
      className={cn(
        'overflow-auto rounded-[var(--radius-default)] border border-[var(--divider)]',
        className,
      )}
    >
      <table
        className="w-full border-collapse text-sm"
        // The real total, not the rendered one. +1 for the header row.
        aria-rowcount={rows.length + 1}
      >
        {/* Visually hidden rather than absent: a caption is how a screen reader user
            knows which of three tables on a page they have landed in. */}
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 z-[var(--z-sticky)] bg-[var(--surface-raised)]">
          <tr aria-rowindex={1}>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                style={column.width ? { width: column.width } : undefined}
                className={cn(
                  'border-b border-[var(--divider)] px-3 py-2 text-2xs font-medium',
                  'uppercase tracking-wide text-[var(--text-muted)]',
                  column.numeric ? 'text-right' : 'text-left',
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {paddingTop > 0 ? (
            <tr aria-hidden="true">
              <td colSpan={columns.length} style={{ height: paddingTop }} />
            </tr>
          ) : null}

          {items.map((item) => {
            const row = rows[item.index];
            if (row === undefined) return null;
            return (
              <tr
                key={rowKey(row)}
                // +2: one for the header row, one because ARIA row indices are 1-based.
                aria-rowindex={item.index + 2}
                style={{ height: rowHeight }}
                tabIndex={onRowActivate ? 0 : undefined}
                onClick={onRowActivate ? () => onRowActivate(row) : undefined}
                onKeyDown={
                  onRowActivate
                    ? (event) => {
                        // Enter and Space, because a row that only responds to a click is
                        // invisible to a keyboard-only dispatcher.
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          onRowActivate(row);
                        }
                      }
                    : undefined
                }
                className={cn(
                  'border-b border-[var(--divider)]',
                  onRowActivate && `cursor-pointer hover:bg-[var(--surface-raised)] ${FOCUS_RING}`,
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      'px-3 py-2 text-[var(--text-primary)]',
                      column.numeric && 'text-right',
                    )}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            );
          })}

          {paddingBottom > 0 ? (
            <tr aria-hidden="true">
              <td colSpan={columns.length} style={{ height: paddingBottom }} />
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
