import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { Ear, MapPin, Send, Square } from 'lucide-react';
import { useAppStore, generateId } from '../../lib/store';
import { streamChat } from '../../lib/sse';
import { fetchSavings, getBase, listenOnceVoice, speakVoice } from '../../lib/api';
import { locationErrorMessage, requestCurrentLocation } from '../../lib/location';
import {
  evaluateLocalWakeText,
  hasWakePhraseFromList,
  nextWakeStatusAfterCommand,
  normalizeWakePhrases,
  shouldRunLocalWakeLoop,
  shouldContinueLocalWakeLoop,
  stripWakePhraseFromList,
  type WakeMode,
} from '../../lib/wake';
import { MicButton } from './MicButton';
import {
  getSpeechRecognitionConstructor,
  getSpeechUnavailableMessage,
  isTauriAppMode,
  requestMicrophonePermission,
  useSpeech,
} from '../../hooks/useSpeech';
import type { ChatMessage, ToolCallInfo, TokenUsage, MessageTelemetry } from '../../types';

function stripThinkTags(text: string): string {
  let cleaned = text.replace(/<think>[\s\S]*?<\/think>\s*/gi, '');
  cleaned = cleaned.replace(/^[\s\S]*?<\/think>\s*/i, '');
  return cleaned.trim();
}

function stripSpeechEmoji(text: string): string {
  let cleaned = text.replace(
    /[\u{1F1E6}-\u{1F1FF}\u{1F300}-\u{1F5FF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{1F700}-\u{1F77F}\u{1F780}-\u{1F7FF}\u{1F800}-\u{1F8FF}\u{1F900}-\u{1F9FF}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}\u2600-\u27BF]+/gu,
    ' ',
  );
  cleaned = cleaned.replace(/[\uFE0E\uFE0F\u200D\u20E3]/g, '');
  return cleaned.replace(/(^|\s)([:;=8xX][-^']?[)(DPpOo/\\]|<3|[ㅋㅎㅠㅜ]{2,})(?=\s|$)/g, ' ');
}

function naturalizeSpeechText(text: string): string {
  const replacements: Record<string, string> = {
    '확인했습니다': '확인했어요',
    '알겠습니다': '알겠어요',
    '완료했습니다': '완료했어요',
    '진행하겠습니다': '진행할게요',
    '도와드리겠습니다': '도와드릴게요',
    '말씀해주세요': '말씀해 주세요',
    '다음과 같습니다': '이렇게 정리했어요',
    '아래와 같습니다': '이렇게 정리했어요',
    '요약하면': '짧게 말하면',
    '참고로': '참고로요',
    '가능합니다': '가능해요',
    '필요합니다': '필요해요',
    '추천합니다': '추천해요',
    'macOS': '맥 오에스',
    'TTS': '티티에스',
    'STT': '에스티티',
    'API': '에이피아이',
    'URL': '유알엘',
    'Chrome': '크롬',
    'Safari': '사파리',
  };
  let spoken = text;
  for (const [oldText, newText] of Object.entries(replacements)) {
    spoken = spoken.split(oldText).join(newText);
  }
  spoken = spoken.replace(/요\s*:\s*/g, '요. ');
  spoken = spoken.replace(/\s*:\s*/g, '은 ');
  spoken = spoken.replace(/\s*[;|]\s*/g, '. ');
  spoken = spoken.replace(/([가-힣])입니다([.!?]?)/g, '$1이에요$2');
  spoken = spoken.replace(/([가-힣])합니다([.!?]?)/g, '$1해요$2');
  spoken = spoken.replace(/([가-힣])됩니다([.!?]?)/g, '$1돼요$2');
  spoken = spoken.split('시이에요').join('시예요');
  return spoken.replace(/\s+/g, ' ').trim();
}

function selectBrowserVoice(preferredVoice: string): SpeechSynthesisVoice | undefined {
  const voices = window.speechSynthesis?.getVoices?.() ?? [];
  const preferred = preferredVoice.trim().toLowerCase();
  if (preferred) {
    const named = voices.find((voice) => voice.name.toLowerCase().includes(preferred));
    if (named) return named;
  }
  return voices.find((voice) => voice.lang.toLowerCase() === 'ko-kr')
    ?? voices.find((voice) => voice.lang.toLowerCase().startsWith('ko'));
}

export function InputArea() {
  const [input, setInput] = useState('');
  const [ttsStatus, setTtsStatus] = useState('');
  const [wakeListening, setWakeListening] = useState(false);
  const [wakeMode, setWakeMode] = useState<WakeMode>('idle');
  const [wakeMessage, setWakeMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const ttsAbortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const wakeRecognitionRef = useRef<any>(null);
  const awaitingWakeCommandRef = useRef(false);
  const wakeLastDetectedAtRef = useRef(0);
  const wakeSendingRef = useRef(false);
  const wakeLoopAbortRef = useRef<AbortController | null>(null);
  const wakeLoopRunningRef = useRef(false);
  const wakeListeningRef = useRef(false);
  const wakeStopRequestedRef = useRef(false);
  const wakeManualPausedRef = useRef(false);
  const wakeAutoStartAttemptedRef = useRef(false);
  const wakeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendMessageRef = useRef<(overrideText?: string) => Promise<void>>(async () => {});

  const activeId = useAppStore((s) => s.activeId);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const streamState = useAppStore((s) => s.streamState);
  const messages = useAppStore((s) => s.messages);
  const currentLocation = useAppStore((s) => s.currentLocation);
  const locationStatus = useAppStore((s) => s.locationStatus);
  const setCurrentLocation = useAppStore((s) => s.setCurrentLocation);
  const setLocationStatus = useAppStore((s) => s.setLocationStatus);
  const speechEnabled = useAppStore((s) => s.settings.speechEnabled);
  const speechInputMode = useAppStore((s) => s.settings.speechInputMode);
  const wakeAlwaysOn = useAppStore((s) => s.settings.wakeAlwaysOn);
  const wakePhraseSetting = useAppStore((s) => s.settings.wakePhrases);
  const speakReplies = useAppStore((s) => s.settings.speakReplies);
  const ttsMode = useAppStore((s) => s.settings.ttsMode);
  const ttsVoice = useAppStore((s) => s.settings.ttsVoice);
  const ttsRate = useAppStore((s) => s.settings.ttsRate);
  const ttsMaxChars = useAppStore((s) => s.settings.ttsMaxChars);
  const ttsPauseMs = useAppStore((s) => s.settings.ttsPauseMs);
  const ttsNaturalize = useAppStore((s) => s.settings.ttsNaturalize);
  const geminiApiKey = useAppStore((s) => s.settings.geminiApiKey);
  const geminiVoice = useAppStore((s) => s.settings.geminiVoice);
  const edgeVoice = useAppStore((s) => s.settings.edgeVoice);
  const tmapApiKey = useAppStore((s) => s.settings.tmapApiKey);
  const navigationMode = useAppStore((s) => s.settings.navigationMode);
  const manualLocationName = useAppStore((s) => s.settings.manualLocationName);
  const updateSettings = useAppStore((s) => s.updateSettings);
  const maxTokens = useAppStore((s) => s.settings.maxTokens);
  const temperature = useAppStore((s) => s.settings.temperature);
  const createConversation = useAppStore((s) => s.createConversation);
  const addMessage = useAppStore((s) => s.addMessage);
  const updateLastAssistant = useAppStore((s) => s.updateLastAssistant);
  const setStreamState = useAppStore((s) => s.setStreamState);
  const resetStream = useAppStore((s) => s.resetStream);
  const modelLoading = useAppStore((s) => s.modelLoading);

  const {
    state: speechState,
    error: speechError,
    statusMessage: speechStatusMessage,
    available: speechAvailable,
    startRecording,
    stopRecording,
    isTranscribing,
  } = useSpeech();
  const wakePhrases = useMemo(
    () => normalizeWakePhrases(wakePhraseSetting),
    [wakePhraseSetting],
  );

  // Abort in-flight stream when the user switches models mid-generation.
  // This prevents errors from trying to continue a stream with a stale model.
  const prevModelRef = useRef(selectedModel);
  useEffect(() => {
    if (prevModelRef.current !== selectedModel && streamState.isStreaming) {
      abortRef.current?.abort();
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      resetStream();
      abortRef.current = null;
    }
    prevModelRef.current = selectedModel;
  }, [selectedModel, streamState.isStreaming, resetStream]);

  const freeWebSpeechUnavailable =
    speechInputMode === 'free_web_speech' && !getSpeechRecognitionConstructor();
  const micDisabled = !speechEnabled || streamState.isStreaming || freeWebSpeechUnavailable;
  const micReason: 'not-enabled' | 'unsupported' | 'streaming' | undefined =
    !speechEnabled ? 'not-enabled'
    : freeWebSpeechUnavailable ? 'unsupported'
    : !speechAvailable && !isTauriAppMode() ? 'unsupported'
    : streamState.isStreaming ? 'streaming'
    : undefined;

  const handleMicClick = useCallback(async () => {
    if (speechState === 'recording') {
      if (isTauriAppMode() && !getSpeechRecognitionConstructor()) return;
      try {
        const text = await stopRecording();
        if (text) {
          setInput((prev) => (prev ? prev + ' ' + text : text));
          textareaRef.current?.focus();
        }
      } catch {
        // Error is captured in useSpeech
      }
    } else {
      await startRecording('ko-KR', (text) => {
        setInput((prev) => (prev ? prev + ' ' + text : text));
        textareaRef.current?.focus();
      }, speechInputMode);
    }
  }, [speechInputMode, speechState, startRecording, stopRecording]);

  const clearWakeTimer = useCallback(() => {
    if (wakeTimerRef.current) {
      clearTimeout(wakeTimerRef.current);
      wakeTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    wakeListeningRef.current = wakeListening;
  }, [wakeListening]);

  const stopWakeLoop = useCallback((showStopped = true, manual = true) => {
    wakeStopRequestedRef.current = true;
    if (manual) wakeManualPausedRef.current = true;
    wakeListeningRef.current = false;
    clearWakeTimer();
    wakeLoopAbortRef.current?.abort();
    wakeLoopAbortRef.current = null;
    wakeLoopRunningRef.current = false;
    awaitingWakeCommandRef.current = false;
    wakeSendingRef.current = false;
    setWakeListening(false);
    setWakeMode('idle');
    setWakeMessage(showStopped ? '호출 대기 중지됨' : '');
  }, [clearWakeTimer]);

  const handleWakeToggle = useCallback(async () => {
    if (wakeListening) {
      stopWakeLoop();
      return;
    }
    if (!speechEnabled) {
      setWakeMode('error');
      setWakeMessage('음성 입력을 먼저 켜주세요');
      return;
    }
    if (isTauriAppMode()) {
      wakeStopRequestedRef.current = false;
      wakeManualPausedRef.current = false;
      wakeListeningRef.current = true;
      setWakeListening(true);
      return;
    }
    if (!getSpeechRecognitionConstructor()) {
      setWakeMode('error');
      setWakeMessage(
        isTauriAppMode()
          ? '앱 모드의 로컬 연속 wake listening은 listen-once STT가 안정화된 뒤 추가됩니다.'
          : getSpeechUnavailableMessage(),
      );
      return;
    }
    try {
      await requestMicrophonePermission();
      wakeStopRequestedRef.current = false;
      wakeManualPausedRef.current = false;
      wakeListeningRef.current = true;
      setWakeListening(true);
    } catch (err) {
      setWakeMode('error');
      setWakeMessage(err instanceof Error ? err.message : '마이크 권한 확인에 실패했습니다');
    }
  }, [speechEnabled, stopWakeLoop, wakeListening]);

  useEffect(() => {
    if (!wakeListening || !isTauriAppMode()) return;
    const handleVisibilityChange = () => {
      if (document.hidden) stopWakeLoop(false, false);
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [stopWakeLoop, wakeListening]);

  useEffect(() => {
    if (!wakeAlwaysOn) {
      wakeAutoStartAttemptedRef.current = false;
      wakeManualPausedRef.current = false;
      return;
    }
    if (
      wakeListening
      || !speechEnabled
      || modelLoading
      || wakeManualPausedRef.current
      || wakeAutoStartAttemptedRef.current
    ) {
      return;
    }
    wakeAutoStartAttemptedRef.current = true;
    void handleWakeToggle();
  }, [handleWakeToggle, modelLoading, speechEnabled, wakeAlwaysOn, wakeListening]);

  const handleUseCurrentLocation = useCallback(async () => {
    updateSettings({ locationAlwaysOn: true });
    setLocationStatus('위치 권한 확인 중');
    try {
      const location = await requestCurrentLocation();
      setCurrentLocation(location);
      setLocationStatus('현재 위치 사용 중');
    } catch (err) {
      setCurrentLocation(null);
      setLocationStatus(locationErrorMessage(err));
    }
  }, [setCurrentLocation, setLocationStatus, updateSettings]);

  const stopTts = useCallback((notifyBackend = true) => {
    ttsAbortRef.current?.abort();
    ttsAbortRef.current = null;
    try {
      window.speechSynthesis?.cancel?.();
    } catch {}
    if (notifyBackend && isTauriAppMode()) {
      void speakVoice({ stop: true }).catch(() => {});
    }
  }, []);

  const cleanSpeechText = useCallback((text: string) => {
    let cleaned = stripThinkTags(text);
    cleaned = cleaned.replace(/```[\s\S]*?```/g, ' ');
    cleaned = cleaned.replace(/`[^`]+`/g, ' ');
    cleaned = cleaned.replace(/https?:\/\/\S+/g, ' ');
    cleaned = cleaned.replace(/^\s*[-*•]\s+/gm, '');
    cleaned = cleaned.replace(/^\s*\d+[.)]\s+/gm, '');
    cleaned = cleaned.replace(/#{1,6}\s*/g, '');
    cleaned = cleaned.replace(/\*\*([^*]+)\*\*/g, '$1');
    cleaned = cleaned.replace(/\b(ollama|tokens?|token\/sec|cost comparison)\b/gi, ' ');
    cleaned = cleaned.replace(/Traceback \(most recent call last\):[\s\S]*/g, ' ');
    cleaned = stripSpeechEmoji(cleaned);
    if (ttsNaturalize ?? true) cleaned = naturalizeSpeechText(cleaned);
    cleaned = cleaned.replace(/\s+/g, ' ').trim();
    return cleaned.slice(0, Math.max(1, ttsMaxChars || 400));
  }, [ttsMaxChars, ttsNaturalize]);

  const speakWithBrowser = useCallback((text: string): boolean => {
    if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) {
      return false;
    }
    const spoken = cleanSpeechText(text);
    if (!spoken) return true;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(spoken);
    utterance.lang = 'ko-KR';
    const voice = selectBrowserVoice(ttsVoice || '');
    if (voice) utterance.voice = voice;
    utterance.rate = Math.max(0.75, Math.min((ttsRate || 165) / 175, 1.15));
    utterance.pitch = 1.02;
    utterance.onerror = () => {
      const message = '음성 응답을 사용할 수 없습니다. TTS 설정을 확인해주세요.';
      setTtsStatus(message);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'warn',
        category: 'chat',
        message,
      });
    };
    utterance.onstart = () => setTtsStatus('음성 응답 중...');
    utterance.onend = () => setTtsStatus('');
    window.speechSynthesis.speak(utterance);
    return true;
  }, [cleanSpeechText, ttsRate, ttsVoice]);

  const speakReply = useCallback((text: string) => {
    if (!speakReplies) {
      setTtsStatus('음성 응답이 꺼져 있습니다.');
      return;
    }
    if (ttsMode === 'disabled') {
      setTtsStatus('음성 응답이 꺼져 있습니다.');
      return;
    }
    stopTts(false);
    const backendTtsModes = new Set([
      'macos_say',
      'gemini_tts',
      'edge_tts',
      'elevenlabs',
      'piper',
    ]);
    if (backendTtsModes.has(ttsMode)) {
      const controller = new AbortController();
      ttsAbortRef.current = controller;
      setTtsStatus('음성 응답 중...');
      void speakVoice({
        text,
        mode: ttsMode,
        voice: ttsVoice || 'Yuna',
        rate: ttsRate || 165,
        max_chars: ttsMaxChars || 400,
        pause_ms: ttsPauseMs ?? 250,
        naturalize: ttsNaturalize ?? true,
        gemini_api_key: ttsMode === 'gemini_tts' ? geminiApiKey.trim() : undefined,
        gemini_voice: ttsMode === 'gemini_tts' ? geminiVoice : undefined,
        edge_voice: ttsMode === 'edge_tts' ? edgeVoice : undefined,
      }, controller.signal)
        .then((result) => {
          if (ttsAbortRef.current === controller) ttsAbortRef.current = null;
          if (result.ok) {
            setTtsStatus(result.message || '음성 응답 중...');
            return;
          }
          const fallbackWorked = speakWithBrowser(text);
          if (!fallbackWorked) setTtsStatus(result.message || 'TTS 음성을 찾을 수 없습니다. macOS 음성 설정을 확인해주세요.');
        })
        .catch((err: any) => {
          if (err?.name === 'AbortError') return;
          const fallbackWorked = speakWithBrowser(text);
          if (!fallbackWorked) setTtsStatus('음성 응답을 사용할 수 없습니다. TTS 설정을 확인해주세요.');
        });
      return;
    }
    if (speakWithBrowser(text)) return;
    try {
      setTtsStatus('음성 응답을 사용할 수 없습니다. TTS 설정을 확인해주세요.');
    } catch {
      const message = '음성 응답을 사용할 수 없습니다. TTS 설정을 확인해주세요.';
      setTtsStatus(message);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(),
        level: 'warn',
        category: 'chat',
        message,
      });
    }
  }, [edgeVoice, geminiApiKey, geminiVoice, speakReplies, speakWithBrowser, stopTts, ttsMaxChars, ttsMode, ttsNaturalize, ttsPauseMs, ttsRate, ttsVoice]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, [input]);

  const stopStreaming = useCallback(() => {
    stopTts();
    abortRef.current?.abort();
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    resetStream();
  }, [resetStream, stopTts]);

  const sendMessage = useCallback(async (overrideText?: string) => {
    const content = (overrideText ?? input).trim();
    if (!content || streamState.isStreaming) return;
    stopTts();

    if (!overrideText) setInput('');

    let convId = activeId;
    if (!convId) {
      convId = createConversation(selectedModel);
    }

    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: Date.now(),
    };
    addMessage(convId, userMsg);

    // Build API messages before adding assistant placeholder
    const currentMessages = useAppStore.getState().messages;
    const apiMessages = currentMessages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const assistantMsg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
    };
    addMessage(convId, assistantMsg);

    // Start streaming
    const startTime = Date.now();
    const timer = setInterval(() => {
      setStreamState({ elapsedMs: Date.now() - startTime });
    }, 100);
    timerRef.current = timer;

    const controller = new AbortController();
    abortRef.current = controller;

    let accumulatedContent = '';
    let usage: TokenUsage | undefined;
    let complexity: { score: number; tier: string; suggested_max_tokens: number } | undefined;
    const toolCalls: ToolCallInfo[] = [];
    let lastFlush = 0;
    let ttftMs: number | undefined;

    setStreamState({
      isStreaming: true,
      phase: 'Generating...',
      elapsedMs: 0,
      activeToolCalls: [],
      content: '',
    });
    useAppStore.getState().addLogEntry({
      timestamp: Date.now(),
      level: 'info',
      category: 'chat',
      message: `Request: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}" → ${selectedModel}`,
    });

    const fridayContext = {
      ...(currentLocation
        ? {
            current_location: {
              name: manualLocationName || '현재 위치',
              latitude: currentLocation.latitude,
              longitude: currentLocation.longitude,
              timezone: currentLocation.timezone,
            },
          }
        : {}),
      navigation: {
        ...(tmapApiKey.trim() ? { tmap_api_key: tmapApiKey.trim() } : {}),
        mode: navigationMode,
      },
    };

    try {
      for await (const sseEvent of streamChat(
        {
          model: selectedModel,
          messages: apiMessages,
          stream: true,
          temperature,
          max_tokens: maxTokens,
          friday_context: fridayContext,
        },
        controller.signal,
      )) {
        const eventName = sseEvent.event;

        if (eventName === 'agent_turn_start') {
          setStreamState({ phase: 'Agent thinking...' });
        } else if (eventName === 'inference_start') {
          setStreamState({ phase: 'Generating...' });
          useAppStore.getState().addLogEntry({
            timestamp: Date.now(), level: 'info', category: 'chat',
            message: `Generating with ${selectedModel}...`,
          });
        } else if (eventName === 'tool_call_start') {
          try {
            const data = JSON.parse(sseEvent.data);
            const tc: ToolCallInfo = {
              id: generateId(),
              tool: data.tool,
              arguments: data.arguments || '',
              status: 'running',
            };
            toolCalls.push(tc);
            setStreamState({
              phase: `Calling ${data.tool}...`,
              activeToolCalls: [...toolCalls],
            });
            updateLastAssistant(convId, accumulatedContent, [...toolCalls]);
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(), level: 'info', category: 'tool',
              message: `Calling ${data.tool}(${data.arguments || ''})`,
            });
          } catch {}
        } else if (eventName === 'tool_call_end') {
          try {
            const data = JSON.parse(sseEvent.data);
            const tc = toolCalls.find(
              (t) => t.tool === data.tool && t.status === 'running',
            );
            if (tc) {
              tc.status = data.success ? 'success' : 'error';
              tc.latency = data.latency;
              tc.result = data.result;
            }
            setStreamState({
              phase: 'Generating...',
              activeToolCalls: [...toolCalls],
            });
            updateLastAssistant(convId, accumulatedContent, [...toolCalls]);
          } catch {}
        } else {
          try {
            const data = JSON.parse(sseEvent.data);
            const delta = data.choices?.[0]?.delta;
            if (data.usage) usage = data.usage;
            if (data.complexity) complexity = data.complexity;
            if (delta?.content) {
              if (!ttftMs) ttftMs = Date.now() - startTime;
              accumulatedContent += delta.content;
              setStreamState({ content: accumulatedContent, phase: '' });

              const now = Date.now();
              if (now - lastFlush >= 80) {
                updateLastAssistant(
                  convId,
                  accumulatedContent,
                  toolCalls.length > 0 ? [...toolCalls] : undefined,
                );
                lastFlush = now;
              }
            }
            if (data.choices?.[0]?.finish_reason === 'stop') break;
          } catch {}
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        // User cancelled or model switch — keep whatever was accumulated
        if (!accumulatedContent) accumulatedContent = '(Generation stopped)';
      } else {
        const errMsg = err?.message || String(err);
        accumulatedContent =
          accumulatedContent || `Error: ${errMsg}`;
        useAppStore.getState().addLogEntry({
          timestamp: Date.now(), level: 'error', category: 'chat',
          message: `Stream error: ${errMsg}`,
        });
      }
    } finally {
      if (!accumulatedContent) {
        accumulatedContent = 'No response was generated. Please try again.';
      }
      const totalMs = Date.now() - startTime;
      const _CLOUD_PREFIXES = ['gpt-', 'o1-', 'o3-', 'o4-', 'claude-', 'gemini-', 'openrouter/', 'MiniMax-', 'chatgpt-'];
      const engineLabel = _CLOUD_PREFIXES.some(p => selectedModel.startsWith(p)) ? 'cloud' : 'ollama';
      const telemetry: MessageTelemetry = {
        engine: engineLabel,
        model_id: selectedModel,
        total_ms: totalMs,
        ttft_ms: ttftMs,
        tokens_per_sec: usage?.completion_tokens
          ? usage.completion_tokens / (totalMs / 1000)
          : undefined,
        complexity_score: complexity?.score,
        complexity_tier: complexity?.tier,
        suggested_max_tokens: complexity?.suggested_max_tokens,
      };
      // Check if the response has digest audio available
      let audioMeta: { url: string } | undefined;
      try {
        const digestRes = await fetch(`${getBase()}/api/digest`);
        if (digestRes.ok) {
          const digest = await digestRes.json();
          if (digest.audio_available) {
            audioMeta = { url: `${getBase()}/api/digest/audio` };
          }
        }
      } catch {
        // Not a digest response or server unavailable — skip
      }

      updateLastAssistant(
        convId,
        accumulatedContent,
        toolCalls.length > 0 ? toolCalls : undefined,
        usage,
        telemetry,
        audioMeta,
      );
      speakReply(accumulatedContent);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      resetStream();
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'chat',
        message: `Response: ${accumulatedContent.length} chars`,
      });
      abortRef.current = null;

      fetchSavings()
        .then((data) => useAppStore.getState().setSavings(data))
        .catch(() => {});
    }
  }, [
    input,
    activeId,
    selectedModel,
    streamState.isStreaming,
    createConversation,
    addMessage,
    updateLastAssistant,
    setStreamState,
    resetStream,
    speakReply,
    stopTts,
    currentLocation,
    tmapApiKey,
    navigationMode,
  ]);

  useEffect(() => {
    sendMessageRef.current = sendMessage;
  }, [sendMessage]);

  useEffect(() => {
    if (!wakeListening || !speechEnabled) {
      clearWakeTimer();
      wakeLoopAbortRef.current?.abort();
      wakeLoopAbortRef.current = null;
      wakeLoopRunningRef.current = false;
      wakeRecognitionRef.current?.stop?.();
      wakeRecognitionRef.current = null;
      awaitingWakeCommandRef.current = false;
      wakeSendingRef.current = false;
      if (wakeListening && !speechEnabled) {
        setWakeMode('error');
        setWakeMessage('음성 입력을 먼저 켜주세요');
      } else if (!wakeListening) {
        setWakeMode('idle');
        setWakeMessage(wakeStopRequestedRef.current ? '호출 대기 중지됨' : '');
      }
      return;
    }

    if (isTauriAppMode()) {
      if (!shouldRunLocalWakeLoop({
        wakeListening,
        speechEnabled,
        appMode: true,
        documentHidden: document.hidden,
      })) {
        clearWakeTimer();
        wakeLoopAbortRef.current?.abort();
        wakeLoopAbortRef.current = null;
        wakeLoopRunningRef.current = false;
        setWakeMode('idle');
        setWakeMessage(wakeStopRequestedRef.current ? '호출 대기 중지됨' : '');
        return;
      }
      if (wakeLoopRunningRef.current) return;
      wakeLoopRunningRef.current = true;
      const controller = new AbortController();
      wakeLoopAbortRef.current = controller;
      let effectDisposed = false;

      const delay = (ms: number) => new Promise<void>((resolve) => {
        if (
          !shouldContinueLocalWakeLoop({
            wakeListening: wakeListeningRef.current,
            stopRequested: wakeStopRequestedRef.current,
            aborted: controller.signal.aborted,
          })
        ) {
          resolve();
          return;
        }
        const timer = window.setTimeout(() => {
          if (wakeTimerRef.current === timer) wakeTimerRef.current = null;
          resolve();
        }, ms);
        wakeTimerRef.current = timer;
        controller.signal.addEventListener('abort', () => {
          if (wakeTimerRef.current === timer) wakeTimerRef.current = null;
          clearTimeout(timer);
          resolve();
        }, { once: true });
      });

      const listenOnce = async (): Promise<string> => {
        try {
          const result = await listenOnceVoice(controller.signal);
          if (result.ok && result.text.trim()) return result.text.trim();
          if (result.message) {
            setWakeMessage(result.message);
            await delay(1200);
          }
        } catch (err: any) {
          if (err?.name !== 'AbortError') {
            setWakeMode('error');
            setWakeMessage('로컬 STT 오류가 발생했습니다');
            await delay(1200);
          }
        }
        return '';
      };

      const runLoop = async () => {
        setWakeMode('wake');
        setWakeMessage('호출어 대기 중');
        while (
          shouldContinueLocalWakeLoop({
            wakeListening: wakeListeningRef.current,
            stopRequested: wakeStopRequestedRef.current,
            aborted: controller.signal.aborted,
          })
        ) {
          if (
            wakeSendingRef.current
            || useAppStore.getState().streamState.isStreaming
          ) {
            await delay(800);
            continue;
          }

          const text = await listenOnce();
          if (
            !shouldContinueLocalWakeLoop({
              wakeListening: wakeListeningRef.current,
              stopRequested: wakeStopRequestedRef.current,
              aborted: controller.signal.aborted,
            })
          ) break;

          const step = evaluateLocalWakeText(text, {
            awaitingCommand: awaitingWakeCommandRef.current,
            lastDetectedAt: wakeLastDetectedAtRef.current,
            now: Date.now(),
            wakePhrases,
          });
          awaitingWakeCommandRef.current = step.awaitingCommand;
          wakeLastDetectedAtRef.current = step.lastDetectedAt;

          if (step.action === 'duplicate_wake' || step.action === 'none') {
            setWakeMode('wake');
            setWakeMessage('호출어 대기 중');
            await delay(400);
            continue;
          }

          if (step.action === 'wake_detected') {
            setWakeMode('detected');
            setWakeMessage('호출어 감지됨');
            await delay(300);
            setWakeMode('command');
            setWakeMessage('명령 듣는 중');
            continue;
          }

          const command = step.command.trim();
          if (!command) {
            setWakeMode('wake');
            setWakeMessage('호출어 대기 중');
            continue;
          }
          wakeSendingRef.current = true;
          setWakeMode('sending');
          setWakeMessage('명령 전송 중');
          await sendMessageRef.current(command);
          wakeSendingRef.current = false;
          if (
            nextWakeStatusAfterCommand({
              wakeListening: wakeListeningRef.current,
              stopRequested: wakeStopRequestedRef.current,
              aborted: controller.signal.aborted,
            }) === 'wake'
          ) {
            setWakeMode('wake');
            setWakeMessage('호출어 대기 중');
          }
          await delay(800);
        }
      };

      void runLoop().finally(() => {
        if (wakeTimerRef.current) {
          clearTimeout(wakeTimerRef.current);
          wakeTimerRef.current = null;
        }
        wakeLoopRunningRef.current = false;
        if (wakeLoopAbortRef.current === controller) wakeLoopAbortRef.current = null;
        wakeSendingRef.current = false;
        if (wakeStopRequestedRef.current) {
          setWakeMode('idle');
          setWakeMessage('호출 대기 중지됨');
        } else if (
          !effectDisposed
          && wakeListeningRef.current
          && speechEnabled
          && !document.hidden
        ) {
          setWakeMode('wake');
          setWakeMessage('호출어 대기 중');
        }
      });

      return () => {
        effectDisposed = true;
        clearWakeTimer();
        controller.abort();
      };
    }

    const Recognition = getSpeechRecognitionConstructor();
    if (!Recognition) {
      setWakeMode('error');
      setWakeMessage(
        isTauriAppMode()
          ? '앱 모드의 로컬 연속 wake listening은 listen-once STT가 안정화된 뒤 추가됩니다.'
          : getSpeechUnavailableMessage(),
      );
      return;
    }

    let stopped = false;
    const recognition = new Recognition();
    wakeRecognitionRef.current = recognition;
    recognition.lang = 'ko-KR';
    recognition.continuous = true;
    recognition.interimResults = false;
    setWakeMode('wake');
    setWakeMessage('호출어 대기 중');

    recognition.onresult = (event: any) => {
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        if (!event.results[i].isFinal) continue;
        const text = String(event.results[i][0]?.transcript || '').trim();
        if (!text) continue;
        const now = Date.now();

        if (awaitingWakeCommandRef.current) {
          if (
            hasWakePhraseFromList(text, wakePhrases)
            && !stripWakePhraseFromList(text, wakePhrases)
          ) {
            wakeLastDetectedAtRef.current = now;
            setWakeMode('command');
            setWakeMessage('명령 듣는 중');
            continue;
          }
          const commandText = hasWakePhraseFromList(text, wakePhrases)
            ? stripWakePhraseFromList(text, wakePhrases)
            : text;
          if (!commandText) continue;
          awaitingWakeCommandRef.current = false;
          wakeSendingRef.current = true;
          setWakeMode('sending');
          setWakeMessage('명령 전송 중');
          void sendMessageRef.current(commandText);
          setTimeout(() => {
            wakeSendingRef.current = false;
            if (wakeListening) {
              setWakeMode('wake');
              setWakeMessage('호출어 대기 중');
            }
          }, 800);
          return;
        }

        if (
          hasWakePhraseFromList(text, wakePhrases)
          && now - wakeLastDetectedAtRef.current > 1500
        ) {
          wakeLastDetectedAtRef.current = now;
          setWakeMode('detected');
          setWakeMessage('호출어 감지됨');
          const command = stripWakePhraseFromList(text, wakePhrases);
          if (command) {
            wakeSendingRef.current = true;
            setWakeMode('sending');
            setWakeMessage('명령 전송 중');
            void sendMessageRef.current(command);
            setTimeout(() => {
              wakeSendingRef.current = false;
              if (wakeListening) {
                setWakeMode('wake');
                setWakeMessage('호출어 대기 중');
              }
            }, 800);
          } else {
            awaitingWakeCommandRef.current = true;
            setWakeMode('command');
            setWakeMessage('명령 듣는 중');
          }
        }
      }
    };
    recognition.onerror = () => {
      if (wakeSendingRef.current) return;
      setWakeMode('error');
      setWakeMessage('마이크 오류가 발생했습니다');
    };
    recognition.onend = () => {
      if (!stopped && wakeListening) {
        try {
          recognition.start();
        } catch {
          setWakeMode('error');
          setWakeMessage('호출 대기 재시작 실패');
        }
      }
    };

    try {
      recognition.start();
    } catch {
      setWakeMode('error');
      setWakeMessage('호출 대기 시작 실패');
    }

    return () => {
      stopped = true;
      awaitingWakeCommandRef.current = false;
      wakeSendingRef.current = false;
      recognition.stop();
      if (wakeRecognitionRef.current === recognition) wakeRecognitionRef.current = null;
    };
  }, [clearWakeTimer, wakeListening, speechEnabled, wakePhrases]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="px-4 pb-4 pt-2" style={{ maxWidth: 'var(--chat-max-width)', margin: '0 auto', width: '100%' }}>
      <div
        className="flex items-end gap-2 rounded-lg px-3 py-3 transition-shadow"
        style={{
          background: 'var(--color-input-bg)',
          border: '1px solid var(--color-input-border)',
          boxShadow: 'var(--shadow-lg)',
          backdropFilter: 'blur(18px)',
          WebkitBackdropFilter: 'blur(18px)',
        }}
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="명령 또는 질문 입력"
          rows={1}
          className="flex-1 bg-transparent outline-none resize-none text-sm leading-relaxed py-1.5"
          style={{ color: 'var(--color-text)', maxHeight: '200px', minHeight: '34px' }}
          disabled={streamState.isStreaming || modelLoading}
        />
        {streamState.isStreaming ? (
          <button
            onClick={stopStreaming}
            className="p-2 rounded-lg transition-colors shrink-0 cursor-pointer"
            style={{ background: 'var(--color-error)', color: 'var(--color-on-accent)' }}
            title="Stop generating"
          >
            <Square size={16} />
          </button>
        ) : (
          <div className="flex items-center gap-1">
            <MicButton
              state={speechState}
              onClick={handleMicClick}
              disabled={micDisabled}
              reason={micReason}
            />
            <button
              onClick={handleUseCurrentLocation}
              disabled={streamState.isStreaming || modelLoading}
              className="p-2 rounded-lg transition-colors shrink-0 cursor-pointer disabled:opacity-30 disabled:cursor-default"
              style={{
                background: currentLocation ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                color: currentLocation ? 'white' : 'var(--color-text-tertiary)',
              }}
              title="Use current location for weather"
            >
              <MapPin size={16} />
            </button>
            <button
              onClick={wakeListening ? () => stopWakeLoop() : handleWakeToggle}
              disabled={!speechEnabled || modelLoading}
              className="p-2 rounded-lg transition-colors shrink-0 cursor-pointer disabled:opacity-30 disabled:cursor-default"
              style={{
                background: wakeListening ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                color: wakeListening ? 'white' : 'var(--color-text-tertiary)',
              }}
              title={wakeListening ? '호출 대기 중지' : '상시 호출 대기'}
              aria-label={wakeListening ? '호출 대기 중지' : '상시 호출 대기'}
            >
              {wakeListening ? <Square size={16} /> : <Ear size={16} />}
            </button>
            <button
              onClick={() => sendMessage()}
              disabled={!input.trim() || modelLoading}
              className="p-2 rounded-lg transition-colors shrink-0 cursor-pointer disabled:opacity-30 disabled:cursor-default"
              style={{
                background: input.trim() ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                color: input.trim() ? 'white' : 'var(--color-text-tertiary)',
              }}
              title="Send message"
            >
              <Send size={16} />
            </button>
          </div>
        )}
      </div>
      <div className="flex items-center justify-center mt-2 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>
          {locationStatus ? locationStatus : ''}
          {speechState === 'recording' ? ' · 듣는 중...' : ''}
          {isTranscribing ? ' · 음성 인식 중...' : ''}
          {speechStatusMessage && speechState === 'idle' ? ` · ${speechStatusMessage}` : ''}
          {speechError ? ` · ${speechError}` : ''}
          {ttsStatus ? ` · ${ttsStatus}` : ''}
          {wakeMessage ? ` · 상시 호출: ${wakeMessage}` : ''}
        </span>
      </div>
    </div>
  );
}
