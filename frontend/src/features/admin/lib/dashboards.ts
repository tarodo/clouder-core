import type { DashboardName } from '../hooks/useAnalytics';

export type ChartKind = 'line' | 'bar';

// One panel = one named query in the route payload (its `dataKey`), rendered as
// a chart + table. A dashboard can have several panels for the §11 cross-fact metrics.
export interface PanelSpec {
  dataKey: string;
  titleKey: string;
  chart: ChartKind;
  xKey: string;
  series: { key: string; labelKey: string }[];
}

export interface DashboardSpec {
  name: DashboardName;
  titleKey: string;
  panels: PanelSpec[];
  showFreshness?: boolean;
}

export const DASHBOARDS: DashboardSpec[] = [
  {
    name: 'triage',
    titleKey: 'admin.analytics.triage.title',
    panels: [
      { dataKey: 'rows', titleKey: 'admin.analytics.triage.median', chart: 'line', xKey: 'date',
        series: [{ key: 'median_decision_ms', labelKey: 'admin.analytics.triage.median' }] },
      { dataKey: 'undo', titleKey: 'admin.analytics.triage.undo', chart: 'line', xKey: 'date',
        series: [{ key: 'undo_rate', labelKey: 'admin.analytics.triage.undo' }] },
    ],
  },
  {
    name: 'taste',
    titleKey: 'admin.analytics.taste.title',
    panels: [
      { dataKey: 'rows', titleKey: 'admin.analytics.taste.affinity', chart: 'bar', xKey: 'label',
        series: [
          { key: 'categorized', labelKey: 'admin.analytics.taste.categorized' },
          { key: 'skip_rate', labelKey: 'admin.analytics.taste.skip_rate' },
        ] },
    ],
  },
  {
    name: 'funnel',
    titleKey: 'admin.analytics.funnel.title',
    panels: [
      { dataKey: 'rows', titleKey: 'admin.analytics.funnel.steps', chart: 'bar', xKey: 'step',
        series: [{ key: 'tracks', labelKey: 'admin.analytics.funnel.tracks' }] },
      { dataKey: 'weekly', titleKey: 'admin.analytics.funnel.weekly', chart: 'bar', xKey: 'week',
        series: [{ key: 'tracks', labelKey: 'admin.analytics.funnel.tracks' }] },
    ],
  },
  {
    name: 'playback',
    titleKey: 'admin.analytics.playback.title',
    panels: [
      { dataKey: 'rows', titleKey: 'admin.analytics.playback.listen', chart: 'line', xKey: 'date',
        series: [
          { key: 'median_listen_ratio', labelKey: 'admin.analytics.playback.listen' },
          { key: 'skip_rate', labelKey: 'admin.analytics.playback.skip_rate' },
        ] },
      { dataKey: 'by_category', titleKey: 'admin.analytics.playback.by_category', chart: 'bar', xKey: 'category',
        series: [{ key: 'avg_listen_ratio', labelKey: 'admin.analytics.playback.listen' }] },
      { dataKey: 'seek', titleKey: 'admin.analytics.playback.seek', chart: 'bar', xKey: 'track',
        series: [{ key: 'seeks', labelKey: 'admin.analytics.playback.seeks' }] },
    ],
  },
  {
    name: 'ops',
    titleKey: 'admin.analytics.ops.title',
    panels: [
      { dataKey: 'rows', titleKey: 'admin.analytics.ops.latency', chart: 'bar', xKey: 'phase',
        series: [
          { key: 'p50_duration_ms', labelKey: 'admin.analytics.ops.p50' },
          { key: 'p95_duration_ms', labelKey: 'admin.analytics.ops.p95' },
        ] },
    ],
    showFreshness: true,
  },
];
