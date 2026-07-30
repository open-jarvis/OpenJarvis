import { create } from 'zustand';
import type {
  BrowserHealthInfo,
  CanonicalTask,
  CanonicalTaskEvent,
  CanonicalTaskSource,
  CodexRuntimeHealth,
  PendingApproval,
  SessionSummary,
  SystemHealth,
  TaskArtifactInfo,
  TaskSummary,
  ToolActionInfo,
  ToolHealth,
  ToolManifestInfo,
} from './api';

export type TaskStreamStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'offline';
export type SpeechProviderKind = 'browser' | 'local' | 'disabled';

export interface SpeechCapabilityState {
  sttAvailable: boolean;
  ttsAvailable: boolean;
  sttProvider: SpeechProviderKind;
  ttsProvider: SpeechProviderKind;
  language: string;
  microphonePermission: PermissionState | 'unknown';
  degraded: boolean;
  lastError: string | null;
  recording: boolean;
  speaking: boolean;
}

interface JarvisWorkspaceState {
  sessionId: string;
  activeTaskId: string | null;
  tasks: CanonicalTask[];
  sessions: SessionSummary[];
  timeline: CanonicalTaskEvent[];
  sources: CanonicalTaskSource[];
  approvals: PendingApproval[];
  actions: ToolActionInfo[];
  artifacts: TaskArtifactInfo[];
  tools: ToolManifestInfo[];
  browserHealth: BrowserHealthInfo[];
  toolHealth: ToolHealth | null;
  codexHealth: CodexRuntimeHealth | null;
  systemHealth: SystemHealth | null;
  taskSummary: TaskSummary | null;
  loading: boolean;
  sending: boolean;
  streamStatus: TaskStreamStatus;
  streamAttempts: number;
  lastSequence: number;
  error: string | null;
  speech: SpeechCapabilityState;
  setSession: (sessionId: string, taskId?: string | null) => void;
  newSession: () => void;
  setTasks: (tasks: CanonicalTask[]) => void;
  setSessions: (sessions: SessionSummary[]) => void;
  upsertTask: (task: CanonicalTask) => void;
  setTimeline: (events: CanonicalTaskEvent[]) => void;
  mergeTimeline: (events: CanonicalTaskEvent[]) => void;
  setSources: (sources: CanonicalTaskSource[]) => void;
  setApprovals: (approvals: PendingApproval[]) => void;
  setActions: (actions: ToolActionInfo[]) => void;
  setArtifacts: (artifacts: TaskArtifactInfo[]) => void;
  setTools: (tools: ToolManifestInfo[]) => void;
  setHealth: (values: {
    browserHealth?: BrowserHealthInfo[];
    toolHealth?: ToolHealth | null;
    codexHealth?: CodexRuntimeHealth | null;
    systemHealth?: SystemHealth | null;
    taskSummary?: TaskSummary | null;
  }) => void;
  setLoading: (loading: boolean) => void;
  setSending: (sending: boolean) => void;
  setStream: (status: TaskStreamStatus, attempts?: number) => void;
  setError: (error: string | null) => void;
  setSpeech: (speech: Partial<SpeechCapabilityState>) => void;
}

const SESSION_KEY = 'openjarvis-canonical-session';
const TASK_KEY = 'openjarvis-canonical-task';

function browserValue(key: string): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(key);
}

function remember(key: string, value: string | null): void {
  if (typeof window === 'undefined') return;
  if (value) window.localStorage.setItem(key, value);
  else window.localStorage.removeItem(key);
}

function freshId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function dedupeEvents(events: CanonicalTaskEvent[]): CanonicalTaskEvent[] {
  const byId = new Map<string, CanonicalTaskEvent>();
  for (const event of events) {
    const current = byId.get(event.event_id);
    if (!current || event.sequence >= current.sequence) byId.set(event.event_id, event);
  }
  return [...byId.values()].sort((a, b) => a.sequence - b.sequence);
}

const initialSession = browserValue(SESSION_KEY) || freshId('session');
const initialTask = browserValue(TASK_KEY);
remember(SESSION_KEY, initialSession);

export const useJarvisStore = create<JarvisWorkspaceState>((set) => ({
  sessionId: initialSession,
  activeTaskId: initialTask,
  tasks: [],
  sessions: [],
  timeline: [],
  sources: [],
  approvals: [],
  actions: [],
  artifacts: [],
  tools: [],
  browserHealth: [],
  toolHealth: null,
  codexHealth: null,
  systemHealth: null,
  taskSummary: null,
  loading: true,
  sending: false,
  streamStatus: 'idle',
  streamAttempts: 0,
  lastSequence: 0,
  error: null,
  speech: {
    sttAvailable: false,
    ttsAvailable: false,
    sttProvider: 'disabled',
    ttsProvider: 'disabled',
    language: 'de-DE',
    microphonePermission: 'unknown',
    degraded: false,
    lastError: null,
    recording: false,
    speaking: false,
  },
  setSession: (sessionId, taskId = null) => {
    remember(SESSION_KEY, sessionId);
    remember(TASK_KEY, taskId);
    set({
      sessionId,
      activeTaskId: taskId,
      timeline: [],
      sources: [],
      actions: [],
      artifacts: [],
      taskSummary: null,
      lastSequence: 0,
      error: null,
    });
  },
  newSession: () => {
    const sessionId = freshId('session');
    remember(SESSION_KEY, sessionId);
    remember(TASK_KEY, null);
    set({
      sessionId,
      activeTaskId: null,
      timeline: [],
      sources: [],
      actions: [],
      artifacts: [],
      taskSummary: null,
      lastSequence: 0,
      error: null,
    });
  },
  setTasks: (tasks) => set({ tasks }),
  setSessions: (sessions) => set({ sessions }),
  upsertTask: (task) => set((state) => ({
    tasks: [task, ...state.tasks.filter((item) => item.task_id !== task.task_id)],
  })),
  setTimeline: (timeline) => {
    const next = dedupeEvents(timeline);
    set({ timeline: next, lastSequence: next[next.length - 1]?.sequence ?? 0 });
  },
  mergeTimeline: (events) => set((state) => {
    const timeline = dedupeEvents([...state.timeline, ...events]);
    return { timeline, lastSequence: timeline[timeline.length - 1]?.sequence ?? state.lastSequence };
  }),
  setSources: (sources) => set({ sources }),
  setApprovals: (approvals) => set({ approvals }),
  setActions: (actions) => set({ actions }),
  setArtifacts: (artifacts) => set({ artifacts }),
  setTools: (tools) => set({ tools }),
  setHealth: (values) => set(values),
  setLoading: (loading) => set({ loading }),
  setSending: (sending) => set({ sending }),
  setStream: (streamStatus, streamAttempts = 0) => set({ streamStatus, streamAttempts }),
  setError: (error) => set({ error }),
  setSpeech: (speech) => set((state) => ({ speech: { ...state.speech, ...speech } })),
}));

export function ensureActiveTaskId(): string {
  const state = useJarvisStore.getState();
  if (state.activeTaskId) return state.activeTaskId;
  const taskId = freshId('task');
  remember(TASK_KEY, taskId);
  useJarvisStore.setState({ activeTaskId: taskId });
  return taskId;
}

export { dedupeEvents };
