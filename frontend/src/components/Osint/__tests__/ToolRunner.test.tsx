import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ToolRunner } from '../ToolRunner';

const mockExecOsintTool = vi.hoisted(() => vi.fn());

vi.mock('../../Desktop/lib/api', () => ({
  execOsintTool: mockExecOsintTool,
}));

describe('ToolRunner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders run button and target', () => {
    render(<ToolRunner toolName="nmap" target="scanme.nmap.org" />);

    expect(screen.getByText('Run Tool')).toBeInTheDocument();
    expect(screen.getByText(/Target: scanme.nmap.org/)).toBeInTheDocument();
  });

  it('executes tool and shows output on success', async () => {
    mockExecOsintTool.mockResolvedValue({
      output: 'PORT    STATE SERVICE\n80/tcp  open  http',
      success: true,
    });

    render(<ToolRunner toolName="nmap" target="scanme.nmap.org" />);

    fireEvent.click(screen.getByText('Run Tool'));

    await waitFor(() => {
      expect(screen.getByText(/PORT/)).toBeInTheDocument();
    });

    expect(mockExecOsintTool).toHaveBeenCalledWith(expect.any(String), 'nmap', 'scanme.nmap.org', 60);
  });

  it('shows error output on failure', async () => {
    mockExecOsintTool.mockRejectedValue(new Error('Connection timeout'));

    render(<ToolRunner toolName="nmap" target="scanme.nmap.org" />);

    fireEvent.click(screen.getByText('Run Tool'));

    await waitFor(() => {
      expect(screen.getByText(/Connection timeout/)).toBeInTheDocument();
    });
  });

  it('disables button while loading', async () => {
    mockExecOsintTool.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({ output: 'ok', success: true }), 50)),
    );

    render(<ToolRunner toolName="nmap" target="scanme.nmap.org" />);

    const btn = screen.getByText('Run Tool');
    fireEvent.click(btn);

    expect(screen.getByText('Running…')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Run Tool')).toBeInTheDocument();
    });
  });
});
