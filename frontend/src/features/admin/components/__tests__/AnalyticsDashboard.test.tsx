import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { AnalyticsDashboard } from '../AnalyticsDashboard';
import type { DashboardSpec } from '../../lib/dashboards';

// jsdom has no layout, so stub the chart lib (ResponsiveContainer needs a size).
vi.mock('@mantine/charts', () => ({
  LineChart: () => <div data-testid="line-chart" />,
  BarChart: () => <div data-testid="bar-chart" />,
}));

const useAnalyticsMock = vi.hoisted(() => vi.fn());
vi.mock('../../hooks/useAnalytics', () => ({ useAnalytics: () => useAnalyticsMock() }));

const range = { from: '2026-01-01', to: '2026-02-01' };

function render1(spec: DashboardSpec) {
  render(
    <MantineProvider>
      <AnalyticsDashboard spec={spec} range={range} />
    </MantineProvider>,
  );
}

const triageSpec: DashboardSpec = {
  name: 'triage',
  titleKey: 'admin.analytics.triage.title',
  panels: [
    { dataKey: 'rows', titleKey: 'admin.analytics.triage.median', chart: 'line', xKey: 'date',
      series: [{ key: 'median_decision_ms', labelKey: 'admin.analytics.triage.median' }] },
  ],
};

describe('AnalyticsDashboard', () => {
  it('renders a panel as a table once loaded', () => {
    useAnalyticsMock.mockReturnValue({
      isLoading: false, isError: false,
      data: { rows: [{ date: '2026-01-02', median_decision_ms: 900 }] },
    });
    render1(triageSpec);
    expect(screen.getByTestId('dashboard-triage')).toBeInTheDocument();
    expect(screen.getByText('2026-01-02')).toBeInTheDocument();
    expect(screen.getByText('900')).toBeInTheDocument();
  });

  it('shows error state', () => {
    useAnalyticsMock.mockReturnValue({ isLoading: false, isError: true, data: undefined });
    render1(triageSpec);
    expect(screen.getByText(/failed/i)).toBeInTheDocument();
  });

  it('renders freshness on the ops dashboard', () => {
    useAnalyticsMock.mockReturnValue({
      isLoading: false, isError: false,
      data: {
        rows: [{ phase: 'merge', p95_duration_ms: 120 }],
        freshness: { newest_dt: '2026-01-02', lag_hours: 5 },
      },
    });
    render1({
      name: 'ops',
      titleKey: 'admin.analytics.ops.title',
      panels: [
        { dataKey: 'rows', titleKey: 'admin.analytics.ops.latency', chart: 'bar', xKey: 'phase',
          series: [{ key: 'p95_duration_ms', labelKey: 'admin.analytics.ops.p95' }] },
      ],
      showFreshness: true,
    });
    expect(screen.getByText(/2026-01-02/)).toBeInTheDocument();
  });
});
