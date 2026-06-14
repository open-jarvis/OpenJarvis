import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { HistoryPanel } from '../HistoryPanel';

const mockFetchOsintHistory = vi.hoisted(() => vi.fn());
const mockFetchFavorites = vi.hoisted(() => vi.fn());
const mockFetchOsintToolDetail = vi.hoisted(() => vi.fn());
const mockDeleteHistoryEntry = vi.hoisted(() => vi.fn());
const mockClearHistory = vi.hoisted(() => vi.fn());

vi.mock('../../Desktop/lib/api', () => ({
  fetchOsintHistory: mockFetchOsintHistory,
  fetchFavorites: mockFetchFavorites,
  fetchOsintToolDetail: mockFetchOsintToolDetail,
  deleteHistoryEntry: mockDeleteHistoryEntry,
  clearHistory: mockClearHistory,
}));

describe('HistoryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders tabs', async () => {
    mockFetchOsintHistory.mockResolvedValue({ entries: [] });
    render(<HistoryPanel />);

    await waitFor(() => {
      expect(screen.getByText('History')).toBeInTheDocument();
      expect(screen.getByText('Favorites')).toBeInTheDocument();
      expect(screen.getByText('Recent Targets')).toBeInTheDocument();
    });
  });

  it('shows empty state for history', async () => {
    mockFetchOsintHistory.mockResolvedValue({ entries: [] });
    render(<HistoryPanel />);

    await waitFor(() => {
      expect(screen.getByText(/No history yet/)).toBeInTheDocument();
    });
  });

  it('shows history entries', async () => {
    mockFetchOsintHistory.mockResolvedValue({
      entries: [
        {
          id: '1',
          type: 'scan',
          user_id: 'u1',
          timestamp: new Date().toISOString(),
          target: 'example.com',
          tool_name: null,
          modules: ['dns'],
          results: { ip: '1.2.3.4' },
          output: null,
          success: true,
          metadata: {},
        },
      ],
    });
    render(<HistoryPanel />);

    await waitFor(() => {
      expect(screen.getByText(/Scan: example.com/)).toBeInTheDocument();
    });
  });

  it('shows favorites list', async () => {
    mockFetchOsintHistory.mockResolvedValue({ entries: [] });
    mockFetchFavorites.mockResolvedValue({ favorites: ['nmap'] });
    mockFetchOsintToolDetail.mockResolvedValue({
      name: 'nmap',
      category: 'Network Scanner',
      description: 'Port scanner',
      url: '',
      install_command: '',
      tags: [],
    });

    render(<HistoryPanel />);

    fireEvent.click(screen.getByText('Favorites'));

    await waitFor(() => {
      expect(screen.getByText('nmap')).toBeInTheDocument();
    });
  });

  it('shows recent targets', async () => {
    mockFetchOsintHistory.mockResolvedValue({
      entries: [
        {
          id: '1',
          type: 'scan',
          user_id: 'u1',
          timestamp: new Date().toISOString(),
          target: 'example.com',
          tool_name: null,
          modules: [],
          results: {},
          output: null,
          success: true,
          metadata: {},
        },
      ],
    });
    render(<HistoryPanel />);

    fireEvent.click(screen.getByText('Recent Targets'));

    await waitFor(() => {
      expect(screen.getByText('example.com')).toBeInTheDocument();
    });
  });

  it('clears all history on Clear All click', async () => {
    mockFetchOsintHistory.mockResolvedValue({
      entries: [
        {
          id: '1',
          type: 'scan',
          user_id: 'u1',
          timestamp: new Date().toISOString(),
          target: 'example.com',
          tool_name: null,
          modules: [],
          results: {},
          output: null,
          success: true,
          metadata: {},
        },
      ],
    });
    mockClearHistory.mockResolvedValue({ cleared: 1 });
    vi.stubGlobal('confirm', () => true);

    render(<HistoryPanel />);

    await waitFor(() => {
      expect(screen.getByText('Clear All')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Clear All'));

    await waitFor(() => {
      expect(mockClearHistory).toHaveBeenCalledTimes(1);
      expect(screen.getByText(/No history yet/)).toBeInTheDocument();
    });

    vi.unstubAllGlobals();
  });
});
