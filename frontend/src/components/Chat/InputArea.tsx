import { useState, useRef, useCallback, useEffect } from 'react';
import { Ear, MapPin, Send, Square } from 'lucide-react';
import { useAppStore, generateId } from '../../lib/store';
import { streamChat } from '../../lib/sse';
import { fetchSavings, getBase } from '../../lib/api';
import { hasWakePhrase, stripWakePhrase, type WakeMode } from '../../lib/wake';
import { MicButton } from './MicButton';
import { useSpeech } from '../../hooks/useSpeech';
import type { ChatMessage, ToolCallInfo, TokenUsage, MessageTelemetry } from '../../types';

function stripThinkTags(text: string): string {
  let cleaned = text.replace(/<think>[\s\S]*?<\/think>\s*/gi, '');
  cleaned = cleaned.replace(/^[\s\S]*?<\/think>\s*/i, '');
  return cleaned.trim();
}

export function InputArea() {
  const [input, setInput] = useState('');
  const [wakeListening, setWakeListening] = useState(false);
  const [wakeMode, setWakeMode] = useState<WakeMode>('idle');
  const [wakeMessage, setWakeMessage] = useState('');
  const [weatherLocation, setWeatherLocation] = useState<{
    latitude: number;
    longitude: number;
    timezone: string;
  } | null>(null);
  const [locationStatus, setLocationStatus] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const wakeRecognitionRef = useRef<any>(null);
  const awaitingWakeCommandRef = useRef(false);
  const wakeLastDetectedAtRef = useRef(0);
  const wakeSendingRef = useRef(false);

  const activeId = useAppStore((s) => s.activeId);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const streamState = useAppStore((s) => s.streamState);
  const messages = useAppStore((s) => s.messages);
  const speechEnabled = useAppStore((s) => s.settings.speechEnabled);
  const speakReplies = useAppStore((s) => s.settings.speakReplies);
  const maxTokens = useAppStore((s) => s.settings.maxTokens);
  const temperature = useAppStore((s) => s.settings.temperature);
  const createConversation = useAppStore((s) => s.createConversation);
  const addMessage = useAppStore((s) => s.addMessage);
  const updateLastAssistant = useAppStore((s) => s.updateLastAssistant);
  const setStreamState = useAppStore((s) => s.setStreamState);
  const resetStream = useAppStore((s) => s.resetStream);
  const modelLoading = useAppStore((s) => s.modelLoading);

  const { state: speechState, available: speechAvailable, startRecording, stopRecording } = useSpeech();

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

  const micDisabled = !speechEnabled || !speechAvailable || streamState.isStreaming;
  const micReason: 'not-enabled' | 'unsupported' | 'streaming' | undefined =
    !speechEnabled ? 'not-enabled'
    : !speechAvailable ? 'unsupported'
    : streamState.isStreaming ? 'streaming'
    : undefined;

  const handleMicClick = useCallback(async () => {
    if (speechState === 'recording') {
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
      });
    }
  }, [speechState, startRecording, stopRecording]);

  const handleUseCurrentLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setLocationStatus('위치 사용 불가');
      return;
    }
    setLocationStatus('위치 확인 중...');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setWeatherLocation({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Seoul',
        });
        setLocationStatus('날씨에 현재 위치 사용');
      },
      () => setLocationStatus('위치 권한이 필요합니다'),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 },
    );
  }, []);

  const speakReply = useCallback((text: string) => {
    if (!speakReplies || !('speechSynthesis' in window)) return;
    const spoken = stripThinkTags(text);
    if (!spoken) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(spoken);
    utterance.lang = 'ko-KR';
    window.speechSynthesis.speak(utterance);
  }, [speakReplies]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, [input]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    resetStream();
  }, [resetStream]);

  const sendMessage = useCallback(async (overrideText?: string) => {
    const content = (overrideText ?? input).trim();
    if (!content || streamState.isStreaming) return;

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

    try {
      for await (const sseEvent of streamChat(
        {
          model: selectedModel,
          messages: apiMessages,
          stream: true,
          temperature,
          max_tokens: maxTokens,
          friday_context: weatherLocation
            ? {
                current_location: {
                  name: '현재 위치',
                  latitude: weatherLocation.latitude,
                  longitude: weatherLocation.longitude,
                  timezone: weatherLocation.timezone,
                },
              }
            : undefined,
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
    weatherLocation,
  ]);

  useEffect(() => {
    if (!wakeListening || !speechEnabled || !speechAvailable) {
      wakeRecognitionRef.current?.stop?.();
      wakeRecognitionRef.current = null;
      awaitingWakeCommandRef.current = false;
      wakeSendingRef.current = false;
      if (wakeListening && !speechEnabled) {
        setWakeMode('error');
        setWakeMessage('음성 입력을 먼저 켜주세요');
      } else if (!wakeListening) {
        setWakeMode('idle');
        setWakeMessage('');
      }
      return;
    }

    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      setWakeMode('error');
      setWakeMessage('이 브라우저는 음성 인식을 지원하지 않습니다');
      return;
    }

    let stopped = false;
    const recognition = new Recognition();
    wakeRecognitionRef.current = recognition;
    recognition.lang = 'ko-KR';
    recognition.continuous = true;
    recognition.interimResults = false;
    setWakeMode('wake');
    setWakeMessage('Wake word 대기 중');

    recognition.onresult = (event: any) => {
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        if (!event.results[i].isFinal) continue;
        const text = String(event.results[i][0]?.transcript || '').trim();
        if (!text) continue;
        const now = Date.now();

        if (awaitingWakeCommandRef.current) {
          if (hasWakePhrase(text) && !stripWakePhrase(text)) {
            wakeLastDetectedAtRef.current = now;
            setWakeMode('command');
            setWakeMessage('명령을 듣고 있습니다');
            continue;
          }
          const commandText = hasWakePhrase(text) ? stripWakePhrase(text) : text;
          if (!commandText) continue;
          awaitingWakeCommandRef.current = false;
          wakeSendingRef.current = true;
          setWakeMode('sending');
          setWakeMessage('명령 전송 중');
          sendMessage(commandText);
          setTimeout(() => {
            wakeSendingRef.current = false;
            if (wakeListening) {
              setWakeMode('wake');
              setWakeMessage('Wake word 대기 중');
            }
          }, 800);
          return;
        }

        if (hasWakePhrase(text) && now - wakeLastDetectedAtRef.current > 1500) {
          wakeLastDetectedAtRef.current = now;
          setWakeMode('detected');
          setWakeMessage('Wake word 감지됨');
          const command = stripWakePhrase(text);
          if (command) {
            wakeSendingRef.current = true;
            setWakeMode('sending');
            setWakeMessage('명령 전송 중');
            sendMessage(command);
            setTimeout(() => {
              wakeSendingRef.current = false;
              if (wakeListening) {
                setWakeMode('wake');
                setWakeMessage('Wake word 대기 중');
              }
            }, 800);
          } else {
            awaitingWakeCommandRef.current = true;
            setWakeMode('command');
            setWakeMessage('명령을 듣고 있습니다');
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
          setWakeMessage('Wake listening 재시작 실패');
        }
      }
    };

    try {
      recognition.start();
    } catch {
      setWakeMode('error');
      setWakeMessage('Wake listening 시작 실패');
    }

    return () => {
      stopped = true;
      awaitingWakeCommandRef.current = false;
      wakeSendingRef.current = false;
      recognition.stop();
      if (wakeRecognitionRef.current === recognition) wakeRecognitionRef.current = null;
    };
  }, [wakeListening, speechEnabled, speechAvailable, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="px-4 pb-4 pt-2" style={{ maxWidth: 'var(--chat-max-width)', margin: '0 auto', width: '100%' }}>
      <div
        className="flex items-center gap-2 rounded-2xl px-4 py-3 transition-shadow"
        style={{
          background: 'var(--color-input-bg)',
          border: '1px solid var(--color-input-border)',
          boxShadow: 'var(--shadow-sm)',
        }}
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Message OpenJarvis..."
          rows={1}
          className="flex-1 bg-transparent outline-none resize-none text-sm leading-relaxed"
          style={{ color: 'var(--color-text)', maxHeight: '200px' }}
          disabled={streamState.isStreaming || modelLoading}
        />
        {streamState.isStreaming ? (
          <button
            onClick={stopStreaming}
            className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer"
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
              className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer disabled:opacity-30 disabled:cursor-default"
              style={{
                background: weatherLocation ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                color: weatherLocation ? 'white' : 'var(--color-text-tertiary)',
              }}
              title="Use current location for weather"
            >
              <MapPin size={16} />
            </button>
            <button
              onClick={() => setWakeListening((value) => !value)}
              disabled={!speechEnabled || !speechAvailable || modelLoading}
              className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer disabled:opacity-30 disabled:cursor-default"
              style={{
                background: wakeListening ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                color: wakeListening ? 'white' : 'var(--color-text-tertiary)',
              }}
              title="Friday Listening"
            >
              <Ear size={16} />
            </button>
            <button
              onClick={() => sendMessage()}
              disabled={!input.trim() || modelLoading}
              className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer disabled:opacity-30 disabled:cursor-default"
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
          <kbd className="font-mono">Enter</kbd> to send &middot;{' '}
          <kbd className="font-mono">Shift+Enter</kbd> for new line
          {locationStatus ? ` · ${locationStatus}` : ''}
          {wakeMode !== 'idle' ? ` · Friday Listening: ${wakeMessage}` : ''}
        </span>
      </div>
    </div>
  );
}
