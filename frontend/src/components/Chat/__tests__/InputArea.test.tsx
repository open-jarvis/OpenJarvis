import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { InputArea } from '../InputArea';

const mockUseAppStore = vi.hoisted(() => vi.fn());
const mockGetState = vi.hoisted(() => vi.fn(() => ({ messages: [], setActiveDomainAgent: vi.fn() })));

vi.mock('@/lib/store', () => ({
  useAppStore: Object.assign(mockUseAppStore, { getState: mockGetState }),
  generateId: () => 'test-id',
}));

const mockStreamChat = vi.hoisted(() => vi.fn());

vi.mock('@/lib/sse', () => ({
  streamChat: mockStreamChat,
  streamResearch: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  fetchSavings: vi.fn(() => Promise.resolve({})),
  getBase: vi.fn(() => 'http://localhost:8000'),
  createPlan: vi.fn(),
  fetchModels: vi.fn(() => Promise.resolve([])),
}));

vi.mock('@/lib/connectors-api', () => ({
  listConnectors: vi.fn(() => Promise.resolve([])),
  getSyncStatus: vi.fn(),
}));

vi.mock('@/hooks/useSpeech', () => ({
  useSpeech: () => ({
    state: 'idle',
    available: false,
    startRecording: vi.fn(),
    stopRecording: vi.fn(),
  }),
}));

vi.mock('../MicButton', () => ({
  MicButton: () => <div data-testid="mic-button" />,
}));

const DEFAULT_STREAM_STATE = {
  isStreaming: false,
  phase: '',
  elapsedMs: 0,
  activeToolCalls: [],
  content: '',
};

const DEFAULT_SETTINGS = {
  theme: 'system',
  apiUrl: '',
  fontSize: 'default',
  defaultModel: '',
  defaultAgent: '',
  temperature: 0.7,
  maxTokens: 4096,
  speechEnabled: false,
  planMode: false,
};

function buildMockState(overrides: Record<string, any> = {}) {
  return {
    activeId: null,
    selectedModel: 'llama3.1',
    streamState: DEFAULT_STREAM_STATE,
    messages: [],
    settings: DEFAULT_SETTINGS,
    modelLoading: false,
    deepResearch: false,
    planMode: false,
    activeDomainAgent: null,
    createConversation: vi.fn(() => 'conv-id'),
    addMessage: vi.fn(),
    updateLastAssistant: vi.fn(),
    setStreamState: vi.fn(),
    resetStream: vi.fn(),
    setDeepResearch: vi.fn(),
    setPlanMode: vi.fn(),
    setActiveDomainAgent: vi.fn(),
    addLogEntry: vi.fn(),
    setSavings: vi.fn(),
    incrementSavings: vi.fn(),
    setLiveEnergy: vi.fn(),
    ...overrides,
  };
}

describe('InputArea', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders input and send button', () => {
    const mockState = buildMockState();
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<InputArea />);

    expect(screen.getByPlaceholderText('Message OpenJarvis...')).toBeInTheDocument();
    expect(screen.getByTitle('Send message')).toBeInTheDocument();
  });

  it('shows agent badge when activeDomainAgent is set', () => {
    const setActiveDomainAgent = vi.fn();
    const mockState = buildMockState({
      activeDomainAgent: 'bavaria_booking',
      setActiveDomainAgent,
    });
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );
    mockGetState.mockReturnValue({
      ...mockState,
      setActiveDomainAgent,
    });

    render(<InputArea />);

    const badge = screen.getByText(/Agent: bavaria_booking/);
    expect(badge).toBeInTheDocument();

    fireEvent.click(badge);
    expect(setActiveDomainAgent).toHaveBeenCalledWith(null);
  });

  it('does not show agent badge when no agent is active', () => {
    const mockState = buildMockState();
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<InputArea />);

    expect(screen.queryByText(/Agent:/)).not.toBeInTheDocument();
  });

  it('sends message with agent_id when domain agent is active', async () => {
    const addMessage = vi.fn();
    const updateLastAssistant = vi.fn();
    const setStreamState = vi.fn();
    const resetStream = vi.fn();

    const mockState = buildMockState({
      activeDomainAgent: 'legal_assistant',
      activeId: 'conv-1',
      addMessage,
      updateLastAssistant,
      setStreamState,
      resetStream,
    });
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );
    mockGetState.mockReturnValue(mockState);

    mockStreamChat.mockImplementation(() =>
      (async function* () {
        yield {
          event: 'inference_start',
          data: JSON.stringify({}),
        };
        yield {
          event: 'done',
          data: JSON.stringify({ choices: [{ finish_reason: 'stop' }] }),
        };
      })(),
    );

    render(<InputArea />);

    const textarea = screen.getByPlaceholderText('Message OpenJarvis...');
    fireEvent.change(textarea, { target: { value: 'Check this contract' } });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' });

    await waitFor(() => {
      expect(mockStreamChat).toHaveBeenCalled();
    });

    const callArgs = mockStreamChat.mock.calls[0][0];
    expect(callArgs.agent_id).toBe('legal_assistant');
    expect(callArgs.model).toBe('llama3.1');
    expect(callArgs.stream).toBe(true);
  });

  it('toggles deep research mode', () => {
    const setDeepResearch = vi.fn();
    const mockState = buildMockState({ setDeepResearch });
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<InputArea />);

    const drButton = screen.getByTitle('Deep Research: off');
    fireEvent.click(drButton);
    expect(setDeepResearch).toHaveBeenCalledWith(true);
  });

  it('toggles plan mode', () => {
    const setPlanMode = vi.fn();
    const mockState = buildMockState({ setPlanMode });
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<InputArea />);

    const pmButton = screen.getByTitle('Plan Mode: off');
    fireEvent.click(pmButton);
    expect(setPlanMode).toHaveBeenCalledWith(true);
  });

  it('shows stop button while streaming', () => {
    const mockState = buildMockState({
      streamState: { ...DEFAULT_STREAM_STATE, isStreaming: true },
    });
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<InputArea />);

    expect(screen.getByTitle('Stop generating')).toBeInTheDocument();
    expect(screen.queryByTitle('Send message')).not.toBeInTheDocument();
  });

  it('disables send button when input is empty', () => {
    const mockState = buildMockState();
    mockUseAppStore.mockImplementation((selector: (s: any) => any) =>
      selector(mockState),
    );

    render(<InputArea />);

    const sendButton = screen.getByTitle('Send message');
    expect(sendButton).toBeDisabled();
  });
});
