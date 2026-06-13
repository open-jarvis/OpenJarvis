import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ChatArea } from '../ChatArea';

const mockUseAppStore = vi.hoisted(() => vi.fn());
const mockGetState = vi.hoisted(() => vi.fn());

vi.mock('@/lib/store', () => ({
  useAppStore: Object.assign(mockUseAppStore, { getState: mockGetState }),
  generateId: () => 'test-id',
}));

vi.mock('@/lib/connectors-api', () => ({
  listConnectors: vi.fn(() => Promise.resolve([])),
}));

vi.mock('react-router', () => ({
  useNavigate: () => vi.fn(),
}));

// Mock InputArea to avoid its complex store requirements in ChatArea tests
vi.mock('../InputArea', () => ({
  InputArea: () => <div data-testid="input-area" />,
}));

const DEFAULT_STREAM_STATE = {
  isStreaming: false,
  phase: '',
  elapsedMs: 0,
  activeToolCalls: [],
  content: '',
};

function buildMockState(overrides: Record<string, any> = {}) {
  return {
    messages: [],
    streamState: DEFAULT_STREAM_STATE,
    systemPanelOpen: false,
    toggleSystemPanel: vi.fn(),
    activeDomainAgent: null,
    setActiveDomainAgent: vi.fn(),
    createConversation: vi.fn(() => 'conv-id'),
    ...overrides,
  };
}

describe('ChatArea', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders greeting and domain agent cards when empty', () => {
    const mockState = buildMockState();
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<ChatArea />);

    expect(screen.getByText(/Good /)).toBeInTheDocument();
    expect(
      screen.getByText(/Ask anything\. Your AI runs locally/),
    ).toBeInTheDocument();

    // 6 domain agent cards: Auto + 5 domain agents
    expect(screen.getByText('Auto')).toBeInTheDocument();
    expect(screen.getByText('Bavaria Booking')).toBeInTheDocument();
    expect(screen.getByText('Legal')).toBeInTheDocument();
    expect(screen.getByText('Marketing')).toBeInTheDocument();
    expect(screen.getByText('Operations')).toBeInTheDocument();
    expect(screen.getByText('Security')).toBeInTheDocument();
  });

  it('activates a domain agent and creates conversation on click', () => {
    const setActiveDomainAgent = vi.fn();
    const createConversation = vi.fn(() => 'conv-123');
    const mockState = buildMockState({
      setActiveDomainAgent,
      createConversation,
    });
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<ChatArea />);
    const card = screen.getByText('Bavaria Booking').closest('button');
    expect(card).toBeTruthy();
    fireEvent.click(card!);

    expect(setActiveDomainAgent).toHaveBeenCalledWith('bavaria_booking');
    expect(createConversation).toHaveBeenCalled();
  });

  it('deactivates domain agent when clicking active card', () => {
    const setActiveDomainAgent = vi.fn();
    const mockState = buildMockState({
      activeDomainAgent: 'legal_assistant',
      setActiveDomainAgent,
    });
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<ChatArea />);
    const card = screen.getByText('Legal').closest('button');
    expect(card).toBeTruthy();
    fireEvent.click(card!);

    expect(setActiveDomainAgent).toHaveBeenCalledWith(null);
    expect(mockState.createConversation).not.toHaveBeenCalled();
  });

  it('does not show domain agent cards when messages exist', () => {
    const mockState = buildMockState({
      messages: [
        {
          id: 'msg-1',
          role: 'user',
          content: 'Hello',
          timestamp: Date.now(),
        },
      ],
    });
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<ChatArea />);

    expect(screen.queryByText('Auto')).not.toBeInTheDocument();
    expect(screen.queryByText('Bavaria Booking')).not.toBeInTheDocument();
  });

  it('renders active state styling for selected domain agent', () => {
    const mockState = buildMockState({
      activeDomainAgent: 'security_assistant',
    });
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<ChatArea />);
    const card = screen.getByText('Security').closest('button');
    expect(card).toBeTruthy();
    const style = (card as HTMLElement).style;
    expect(style.border).toContain('rgb(220, 38, 38)');
  });
});
