/**
 * Data display: the table, the dashboard tile, and the two things that surround them.
 *
 * `TrendSparkline`, `EmptyState` and `Pagination` live alongside `StatCard` because they
 * share its one rule - a figure with no context and no timestamp is not shipped.
 */

export { DataTable, type Column, type DataTableProps } from './data-table.js';
export {
  EmptyState,
  Pagination,
  StatCard,
  TrendSparkline,
  type EmptyStateProps,
  type PaginationProps,
  type StatCardProps,
  type TrendSparklineProps,
} from './stat-card.js';
