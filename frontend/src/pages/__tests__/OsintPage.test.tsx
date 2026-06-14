import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { OsintPage } from '../OsintPage';

const mockFetchAlerts = vi.hoisted(() => vi.fn());
const mockFetchSchedules = vi.hoisted(() => vi.fn());

vi.mock('../../../lib/api', () => ({
  fetchOsintAlerts: mockFetchAlerts,
  fetchOsintSchedules: mockFetchSchedules,
}));

describe('OsintPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchAlerts.mockResolvedValue({ alerts: [], count: 0, unread: 0 });
    mockFetchSchedules.mockResolvedValue([]);
  });

  it('renders all tabs', async () => {
    render(<OsintPage />);

    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('Tool Arsenal')).toBeInTheDocument();
    expect(screen.getByText('FBI Watchdog')).toBeInTheDocument();
    expect(screen.getByText('History')).toBeInTheDocument();
    expect(screen.getByText('Scheduler')).toBeInTheDocument();
    expect(screen.getByText('Alerts')).toBeInTheDocument();
  });

  it('switches to alerts tab on click', async () => {
    render(<OsintPage />);

    fireEvent.click(screen.getByText('Alerts'));

    await waitFor(() => {
      expect(screen.getByText(/No change alerts yet/)).toBeInTheDocument();
    });
  });

  it('switches to scheduler tab on click', async () => {
    render(<OsintPage />);

    fireEvent.click(screen.getByText('Scheduler'));

    await waitFor(() => {
      expect(screen.getByText(/No schedules yet/)).toBeInTheDocument();
    });
  });
});
