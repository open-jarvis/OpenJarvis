import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ToolSearch } from '../ToolSearch';

const mockSearchOsintTools = vi.hoisted(() => vi.fn());
const mockFetchOsintCategories = vi.hoisted(() => vi.fn());
const mockExecOsintTool = vi.hoisted(() => vi.fn());

vi.mock('../../Desktop/lib/api', () => ({
  searchOsintTools: mockSearchOsintTools,
  fetchOsintCategories: mockFetchOsintCategories,
  execOsintTool: mockExecOsintTool,
}));

vi.mock('../ToolRunner', () => ({
  ToolRunner: ({ toolName }: { toolName: string }) => (
    <div data-testid={`runner-${toolName}`}>Runner for {toolName}</div>
  ),
}));

describe('ToolSearch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchOsintCategories.mockResolvedValue(['Domain & IP OSINT', 'Email OSINT Tools']);
  });

  it('renders search input and category buttons', async () => {
    render(<ToolSearch />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search OSINT tools...')).toBeInTheDocument();
    });

    expect(screen.getByText('All')).toBeInTheDocument();
    expect(screen.getByText('Domain & IP OSINT')).toBeInTheDocument();
  });

  it('triggers search on category click', async () => {
    mockSearchOsintTools.mockResolvedValue({
      query: '',
      results: [
        {
          name: 'Amass',
          category: 'Domain & IP OSINT',
          description: 'Subdomain enumeration',
          url: 'https://github.com/owasp-amass/amass',
          install_command: 'go install amass',
          tags: ['subdomain'],
        },
      ],
      count: 1,
    });

    render(<ToolSearch />);

    await waitFor(() => {
      expect(screen.getByText('Domain & IP OSINT')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Domain & IP OSINT'));

    await waitFor(() => {
      expect(mockSearchOsintTools).toHaveBeenCalledWith(
        expect.any(String),
        '',
        20,
        'Domain & IP OSINT',
      );
    });

    await waitFor(() => {
      expect(screen.getByText('Amass')).toBeInTheDocument();
    });
  });

  it('shows open button for web tools', async () => {
    mockSearchOsintTools.mockResolvedValue({
      query: 'shodan',
      results: [
        {
          name: 'Shodan',
          category: 'IoT Search Engine',
          description: 'Search engine for devices',
          url: 'https://www.shodan.io',
          install_command: '',
          tags: ['iot'],
        },
      ],
      count: 1,
    });

    render(<ToolSearch />);

    const input = screen.getByPlaceholderText('Search OSINT tools...');
    fireEvent.change(input, { target: { value: 'shodan' } });
    await waitFor(() => expect(input).toHaveValue('shodan'));
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => {
      expect(screen.getByText('Shodan')).toBeInTheDocument();
    });

    expect(screen.getByTitle('Open website')).toBeInTheDocument();
  });

  it('shows run button and expands runner on click', async () => {
    mockSearchOsintTools.mockResolvedValue({
      query: 'amass',
      results: [
        {
          name: 'Amass',
          category: 'Domain & IP OSINT',
          description: 'Subdomain enumeration',
          url: 'https://github.com/owasp-amass/amass',
          install_command: 'go install amass',
          tags: ['subdomain'],
        },
      ],
      count: 1,
    });

    render(<ToolSearch />);

    const input = screen.getByPlaceholderText('Search OSINT tools...');
    fireEvent.change(input, { target: { value: 'amass' } });
    await waitFor(() => expect(input).toHaveValue('amass'));
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => {
      expect(screen.getByText('Amass')).toBeInTheDocument();
    });

    const runButton = screen.getByTitle('Run tool');
    expect(runButton).toBeInTheDocument();

    fireEvent.click(runButton);

    await waitFor(() => {
      expect(screen.getByTestId('runner-Amass')).toBeInTheDocument();
    });
  });

  it('copies install command on copy button click', async () => {
    const clipboardWrite = vi.fn();
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: clipboardWrite },
      writable: true,
      configurable: true,
    });

    mockSearchOsintTools.mockResolvedValue({
      query: 'amass',
      results: [
        {
          name: 'Amass',
          category: 'Domain & IP OSINT',
          description: 'Subdomain enumeration',
          url: 'https://github.com/owasp-amass/amass',
          install_command: 'go install amass',
          tags: ['subdomain'],
        },
      ],
      count: 1,
    });

    render(<ToolSearch />);

    const input = screen.getByPlaceholderText('Search OSINT tools...');
    fireEvent.change(input, { target: { value: 'amass' } });
    await waitFor(() => expect(input).toHaveValue('amass'));
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => {
      expect(screen.getByText('Amass')).toBeInTheDocument();
    });

    const copyButton = screen.getByTitle('Copy install command');
    fireEvent.click(copyButton);

    await waitFor(() => {
      expect(clipboardWrite).toHaveBeenCalledWith('go install amass');
    });
  });
});
