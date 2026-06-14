import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SchedulePanel } from '../SchedulePanel';

const mockFetchSchedules = vi.hoisted(() => vi.fn());
const mockCreateSchedule = vi.hoisted(() => vi.fn());
const mockDeleteSchedule = vi.hoisted(() => vi.fn());
const mockToggleSchedule = vi.hoisted(() => vi.fn());
const mockUpdateSchedule = vi.hoisted(() => vi.fn());
const mockRunScheduleNow = vi.hoisted(() => vi.fn());

vi.mock('../../Desktop/lib/api', () => ({
  fetchSchedules: mockFetchSchedules,
  createSchedule: mockCreateSchedule,
  deleteSchedule: mockDeleteSchedule,
  toggleSchedule: mockToggleSchedule,
  updateSchedule: mockUpdateSchedule,
  runScheduleNow: mockRunScheduleNow,
}));

describe('SchedulePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders empty state', async () => {
    mockFetchSchedules.mockResolvedValue({ schedules: [], count: 0 });
    render(<SchedulePanel />);

    await waitFor(() => {
      expect(screen.getByText(/No schedules yet/)).toBeInTheDocument();
    });
  });

  it('shows schedule list', async () => {
    mockFetchSchedules.mockResolvedValue({
      schedules: [
        {
          id: '1',
          target: 'example.com',
          modules: ['dns', 'whois'],
          interval_minutes: 60,
          last_run: null,
          next_run: null,
          enabled: true,
          created_at: new Date().toISOString(),
        },
      ],
      count: 1,
    });
    render(<SchedulePanel />);

    await waitFor(() => {
      expect(screen.getByText('example.com')).toBeInTheDocument();
    });
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('opens create form on button click', async () => {
    mockFetchSchedules.mockResolvedValue({ schedules: [], count: 0 });
    render(<SchedulePanel />);

    fireEvent.click(screen.getByText('New Schedule'));
    expect(screen.getByPlaceholderText('example.com')).toBeInTheDocument();
  });

  it('creates schedule on form submit', async () => {
    mockFetchSchedules.mockResolvedValue({ schedules: [], count: 0 });
    mockCreateSchedule.mockResolvedValue({ id: '2', target: 'test.com', modules: ['dns'], interval_minutes: 30, enabled: true });

    render(<SchedulePanel />);
    fireEvent.click(screen.getByText('New Schedule'));

    const input = screen.getByPlaceholderText('example.com');
    fireEvent.change(input, { target: { value: 'test.com' } });

    fireEvent.click(screen.getByText('Create Schedule'));

    await waitFor(() => {
      expect(mockCreateSchedule).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ target: 'test.com', modules: expect.any(Array), interval_minutes: expect.any(Number) }),
      );
    });
  });

  it('toggles schedule status', async () => {
    mockFetchSchedules.mockResolvedValue({
      schedules: [
        {
          id: '1',
          target: 'example.com',
          modules: ['dns'],
          interval_minutes: 60,
          last_run: null,
          next_run: null,
          enabled: true,
          created_at: new Date().toISOString(),
        },
      ],
      count: 1,
    });
    mockToggleSchedule.mockResolvedValue({ schedule_id: '1', enabled: false });

    render(<SchedulePanel />);
    await waitFor(() => {
      expect(screen.getByText('example.com')).toBeInTheDocument();
    });

    const pauseBtn = screen.getByTitle('Pause');
    fireEvent.click(pauseBtn);

    await waitFor(() => {
      expect(mockToggleSchedule).toHaveBeenCalledWith(expect.any(String), '1');
    });
  });

  it('opens edit form on edit button click', async () => {
    mockFetchSchedules.mockResolvedValue({
      schedules: [
        {
          id: '1',
          target: 'example.com',
          modules: ['dns', 'whois'],
          interval_minutes: 60,
          last_run: null,
          next_run: null,
          enabled: true,
          created_at: new Date().toISOString(),
        },
      ],
      count: 1,
    });

    render(<SchedulePanel />);
    await waitFor(() => {
      expect(screen.getByText('example.com')).toBeInTheDocument();
    });

    const editBtn = screen.getByTitle('Edit');
    fireEvent.click(editBtn);

    expect(screen.getByDisplayValue('example.com')).toBeInTheDocument();
    expect(screen.getByDisplayValue('60')).toBeInTheDocument();
    expect(screen.getByText('Save')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('updates schedule on edit save', async () => {
    mockFetchSchedules.mockResolvedValue({
      schedules: [
        {
          id: '1',
          target: 'example.com',
          modules: ['dns', 'whois'],
          interval_minutes: 60,
          last_run: null,
          next_run: null,
          enabled: true,
          created_at: new Date().toISOString(),
        },
      ],
      count: 1,
    });
    mockUpdateSchedule.mockResolvedValue({
      id: '1',
      target: 'updated.com',
      modules: ['dns'],
      interval_minutes: 30,
      enabled: true,
      created_at: new Date().toISOString(),
    });

    render(<SchedulePanel />);
    await waitFor(() => {
      expect(screen.getByText('example.com')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle('Edit'));

    const targetInput = screen.getByDisplayValue('example.com');
    fireEvent.change(targetInput, { target: { value: 'updated.com' } });

    const intervalInput = screen.getByDisplayValue('60');
    fireEvent.change(intervalInput, { target: { value: '30' } });

    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(mockUpdateSchedule).toHaveBeenCalledWith(
        expect.any(String),
        '1',
        expect.objectContaining({
          target: 'updated.com',
          interval_minutes: 30,
        }),
      );
    });
  });

  it('cancels edit without saving', async () => {
    mockFetchSchedules.mockResolvedValue({
      schedules: [
        {
          id: '1',
          target: 'example.com',
          modules: ['dns'],
          interval_minutes: 60,
          last_run: null,
          next_run: null,
          enabled: true,
          created_at: new Date().toISOString(),
        },
      ],
      count: 1,
    });

    render(<SchedulePanel />);
    await waitFor(() => {
      expect(screen.getByText('example.com')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle('Edit'));
    expect(screen.getByDisplayValue('example.com')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Cancel'));

    expect(screen.queryByDisplayValue('example.com')).not.toBeInTheDocument();
    expect(mockUpdateSchedule).not.toHaveBeenCalled();
  });

  it('runs schedule now on button click', async () => {
    mockFetchSchedules.mockResolvedValue({
      schedules: [
        {
          id: '1',
          target: 'example.com',
          modules: ['dns'],
          interval_minutes: 60,
          last_run: null,
          next_run: null,
          enabled: true,
          created_at: new Date().toISOString(),
        },
      ],
      count: 1,
    });
    mockRunScheduleNow.mockResolvedValue({ schedule_id: '1', target: 'example.com', success: true, changed: false });

    render(<SchedulePanel />);
    await waitFor(() => {
      expect(screen.getByText('example.com')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle('Run Now'));

    await waitFor(() => {
      expect(mockRunScheduleNow).toHaveBeenCalledWith(expect.any(String), '1');
    });
  });

  it('shows error when run now fails', async () => {
    mockFetchSchedules.mockResolvedValue({
      schedules: [
        {
          id: '1',
          target: 'example.com',
          modules: ['dns'],
          interval_minutes: 60,
          last_run: null,
          next_run: null,
          enabled: true,
          created_at: new Date().toISOString(),
        },
      ],
      count: 1,
    });
    mockRunScheduleNow.mockRejectedValue(new Error('Scan failed'));

    render(<SchedulePanel />);
    await waitFor(() => {
      expect(screen.getByText('example.com')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle('Run Now'));

    await waitFor(() => {
      expect(screen.getByText(/Scan failed/)).toBeInTheDocument();
    });
  });
});
