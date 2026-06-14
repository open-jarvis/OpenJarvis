import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LandhausStatusPanel } from '../LandhausStatusPanel';

const mockFetch = vi.hoisted(() => vi.fn());

global.fetch = mockFetch;

describe('LandhausStatusPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading state initially', () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(<LandhausStatusPanel />);
    expect(screen.getByText(/Loading Landhaus Bavaria status/)).toBeInTheDocument();
  });

  it('renders all source statuses when health data loads', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'ok',
        sources: {
          website: { status: 'up', status_code: 200 },
          deskline: { status: 'up' },
          ical: { status: 'up', content_length: 1234 },
          vercel: { status: 'up', latest_state: 'READY' },
        },
      }),
    });

    render(<LandhausStatusPanel />);

    await waitFor(() => {
      expect(screen.getByText('Website')).toBeInTheDocument();
      expect(screen.getByText('Deskline')).toBeInTheDocument();
      expect(screen.getByText('iCal Sync')).toBeInTheDocument();
      expect(screen.getByText('Vercel')).toBeInTheDocument();
    });

    expect(screen.getAllByText('up').length).toBeGreaterThanOrEqual(4);
  });

  it('shows error state when fetch fails', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    render(<LandhausStatusPanel />);

    await waitFor(() => {
      expect(screen.getByText(/Network error/)).toBeInTheDocument();
    });
  });

  it('shows error state on non-ok HTTP response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
    });

    render(<LandhausStatusPanel />);

    await waitFor(() => {
      expect(screen.getByText(/HTTP 503/)).toBeInTheDocument();
    });
  });

  it('renders demo status correctly', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'ok',
        sources: {
          website: { status: 'up', status_code: 200 },
          deskline: { status: 'demo', rooms_total: 12, rooms_occupied: 8, rooms_available: 4 },
          ical: { status: 'demo', bookings_count: 23, last_sync: '2026-06-14T10:00:00Z' },
          vercel: { status: 'demo', deployment_state: 'READY', production_url: 'https://www.landhausbavaria.de' },
        },
      }),
    });

    render(<LandhausStatusPanel />);

    await waitFor(() => {
      expect(screen.getByText('Website')).toBeInTheDocument();
    });

    const demoItems = screen.getAllByText('demo');
    expect(demoItems.length).toBe(3);
    expect(screen.getByText(/Rooms:/)).toBeInTheDocument();
    expect(screen.getByText(/Bookings:/)).toBeInTheDocument();
    expect(screen.getByText(/Deploy:/)).toBeInTheDocument();
  });

  it('renders down status with error message', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'ok',
        sources: {
          website: { status: 'down', error: 'Connection timeout' },
          deskline: { status: 'demo', rooms_total: 12, rooms_occupied: 8, rooms_available: 4 },
          ical: { status: 'demo', bookings_count: 23 },
          vercel: { status: 'demo', deployment_state: 'READY' },
        },
      }),
    });

    render(<LandhausStatusPanel />);

    await waitFor(() => {
      expect(screen.getByText('Connection timeout')).toBeInTheDocument();
    });
  });

  it('refreshes data when refresh button is clicked', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'ok',
        sources: {
          website: { status: 'up', status_code: 200 },
          deskline: { status: 'up' },
          ical: { status: 'up', content_length: 1234 },
          vercel: { status: 'up', latest_state: 'READY' },
        },
      }),
    });

    render(<LandhausStatusPanel />);

    await waitFor(() => {
      expect(screen.getByText('Refresh')).toBeInTheDocument();
    });

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'ok',
        sources: {
          website: { status: 'up', status_code: 200 },
          deskline: { status: 'up' },
          ical: { status: 'up', content_length: 5678 },
          vercel: { status: 'up', latest_state: 'READY' },
        },
      }),
    });

    const refreshBtn = screen.getByText('Refresh');
    fireEvent.click(refreshBtn);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });
});
