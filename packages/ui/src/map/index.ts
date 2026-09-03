/**
 * The map shell and its layers.
 *
 * MapLibre is an optional peer dependency loaded on mount - see `map-shell.tsx` for why.
 * Nothing in this directory can be imported into a server component.
 */

export {
  MapLegend,
  MapShell,
  gnDivisionLayer,
  heatLayer,
  incidentLayer,
  severityColourExpression,
  type LayerSpec,
  type MapLegendProps,
  type MapShellProps,
} from './map-shell.js';
