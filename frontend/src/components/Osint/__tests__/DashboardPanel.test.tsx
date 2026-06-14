import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { DashboardPanel } from '../DashboardPanel';

const mockFetchDashboardStats = vi.hoisted(() => vi.fn());
const mockFetchAlerts = vi.hoisted(() => vi.fn());

vi.mock('../../Desktop/lib/api', () => ({
  fetchDashboardStats: mockFetchDashboardStats,
  fetchAlerts: mockFetchAlerts,
}));

describe('DashboardPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchAlerts.mockResolvedValue({ alerts: [], count: 0, unread: 0 });
  });

  it('renders summary cards with data', async () => {
    mockFetchDashboardStats.mockResolvedValue({
      total_scans: 5,
      total_execs: 3,
      total_actions: 8,
      unique_targets: 2,
      success_rate: 87.5,
      top_targets: [{ target: 'example.com', count: 3 }],
      tool_usage: [{ tool_name: 'nmap', count: 2 }],
      module_usage: [{ module: 'dns', count: 2 }],
      activity_timeline: [
        { date: '2026-06-01', scans: 1, execs: 0 },
        { date: '2026-06-02', scans: 0, execs: 1 },
      ],
    });

    render(<DashboardPanel />);

    await waitFor(() => {
      expect(screen.getByText('5')).toBeInTheDocument();
      expect(screen.getByText('3')).toBeInTheDocument();
      expect(screen.getByText('87.5%')).toBeInTheDocument();
      expect(screen.getByText('2')).toBeInTheDocument();
    });

    expect(screen.getByText('Total Scans')).toBeInTheDocument();
    expect(screen.getByText('Total Executions')).toBeInTheDocument();
    expect(screen.getByText('Success Rate')).toBeInTheDocument();
    expect(screen.getByText('Unique Targets')).toBeInTheDocument();
  });

  it('shows empty state when no activity', async () => {
    mockFetchDashboardStats.mockResolvedValue({
      total_scans: 0,
      total_execs: 0,
      total_actions: 0,
      unique_targets: 0,
      success_rate: 0,
      top_targets: [],
      tool_usage: [],
      module_usage: [],
      activity_timeline: [],
    });

    render(<DashboardPanel />);

    await waitFor(() => {
      expect(screen.getByText(/No activity yet/)).toBeInTheDocument();
    });
  });

  it('shows charts when data exists', async () => {
    mockFetchDashboardStats.mockResolvedValue({
      total_scans: 10,
      total_execs: 5,
      total_actions: 15,
      unique_targets: 3,
      success_rate: 100,
      top_targets: [
        { target: 'a.com', count: 5 },
        { target: 'b.com', count: 3 },
      ],
      tool_usage: [
        { tool_name: 'nmap', count: 4 },
        { tool_name: 'amass', count: 2 },
      ],
      module_usage: [
        { module: 'dns', count: 5 },
        { module: 'whois', count: 3 },
      ],
      activity_timeline: Array.from({ length: 30 }, (_, i) => ({
        date: `2026-06-${String(i + 1).padStart(2, '0')}`,
        scans: i % 3 === 0 ? 1 : 0,
        execs: i % 5 === 0 ? 1 : 0,
      })),
    });

    render(<DashboardPanel />);

    await waitFor(() => {
      expect(screen.getByText('Activity Timeline (30 days)')).toBeInTheDocument();
    });

    expect(screen.getByText('Top Targets')).toBeInTheDocument();
    expect(screen.getByText('Tool Usage')).toBeInTheDocument();
    expect(screen.getByText('Module Usage')).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    mockFetchDashboardStats.mockRejectedValue(new Error('Network error'));

    render(<DashboardPanel />);

    await waitFor(() => {
      expect(screen.getByText(/Network error/)).toBeInTheDocument();
    });
  });
});
