# Kiosk Assistant Voice Caption Synchronization & Speech Bubble Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide natural visual synchronization between the TTS audio stream and assistant text display on the Kiosk UI, fix the Codex Pet speech bubble narrow width bug, and add dynamic post-speech caption hold and fade-out.

**Architecture:** Split spoken text into completed sentences (70% opacity) and active tail sentence (100% white high contrast) via a pure partitioning helper. Manage post-speech hold duration (proportional to text length) and CSS fade transitions in `usePipecatVoiceMode` without altering conversation persistence. Fix speech bubble flexbox constraints on Codex Pet and supply it with the active sentence teaser.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Vitest, Pipecat RTVI Client.

## Global Constraints
- Target directory: `frontend/` in `/home/robber/Work/jarvis/OpenJarvis`.
- **Zero backend modifications**: Do not touch `src/openjarvis/`.
- **Zero pipeline modifications**: Do not touch Pipecat server pipeline or STT/TTS providers.
- **Surgical changes only**: Touch only the components and hooks directly responsible for assistant captions and speech bubble presentation.
- All tests run via `npm --prefix frontend test` and TypeScript check via `npx --prefix frontend tsc -b`.

---

### Task 1: Caption Partitioning Helper Function (TDD)

**Files:**
- Modify: `frontend/src/components/Chat/voiceTurnRows.ts:10-20`
- Test: `frontend/src/components/Chat/voiceTurnRows.test.ts:50-67`

**Interfaces:**
- Produces:
  ```typescript
  export interface CaptionDisplaySegments {
    completedText: string;
    activeText: string;
  }
  export function partitionCaptionSegments(text: string): CaptionDisplaySegments;
  ```

- [ ] **Step 1: Write failing tests for `partitionCaptionSegments`**

Add tests to `frontend/src/components/Chat/voiceTurnRows.test.ts`:
```typescript
import {
  assistantCaptionDelta,
  currentVoiceTurnRows,
  nextCaptionSegment,
  partitionCaptionSegments,
  splitCaptionSegments,
  voiceCaptionHoldMs,
} from './voiceTurnRows';

describe('partitionCaptionSegments', () => {
  it('handles empty or whitespace strings', () => {
    expect(partitionCaptionSegments('')).toEqual({ completedText: '', activeText: '' });
    expect(partitionCaptionSegments('   ')).toEqual({ completedText: '', activeText: '' });
  });

  it('keeps single sentence as purely active text', () => {
    expect(partitionCaptionSegments('Xin chào quý khách!')).toEqual({
      completedText: '',
      activeText: 'Xin chào quý khách!',
    });
  });

  it('partitions multiple sentences into completed and active segments', () => {
    expect(partitionCaptionSegments('Xin chào quý khách. Tôi có thể giúp gì cho bạn?')).toEqual({
      completedText: 'Xin chào quý khách.',
      activeText: 'Tôi có thể giúp gì cho bạn?',
    });
  });

  it('handles trailing spaces and three sentences properly', () => {
    expect(partitionCaptionSegments('Một. Hai! Ba? ')).toEqual({
      completedText: 'Một. Hai!',
      activeText: 'Ba?',
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
npm --prefix /home/robber/Work/jarvis/OpenJarvis/frontend run test -- src/components/Chat/voiceTurnRows.test.ts
```
Expected: FAIL with `partitionCaptionSegments is not defined`.

- [ ] **Step 3: Implement `partitionCaptionSegments` in `voiceTurnRows.ts`**

Add to `frontend/src/components/Chat/voiceTurnRows.ts`:
```typescript
export interface CaptionDisplaySegments {
  completedText: string;
  activeText: string;
}

export function partitionCaptionSegments(text: string): CaptionDisplaySegments {
  const trimmed = text.trim();
  if (!trimmed) return { completedText: '', activeText: '' };
  const segments = splitCaptionSegments(trimmed);
  if (segments.length <= 1) {
    return { completedText: '', activeText: trimmed };
  }
  const activeText = segments[segments.length - 1] ?? '';
  const completedText = trimmed.slice(0, trimmed.length - activeText.length).trimEnd();
  return { completedText, activeText };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
npm --prefix /home/robber/Work/jarvis/OpenJarvis/frontend run test -- src/components/Chat/voiceTurnRows.test.ts
```
Expected: PASS (all tests pass).

- [ ] **Step 5: Commit**

```bash
cd /home/robber/Work/jarvis/OpenJarvis
git add frontend/src/components/Chat/voiceTurnRows.ts frontend/src/components/Chat/voiceTurnRows.test.ts
git commit -m "feat(kiosk): add partitionCaptionSegments utility for dual-tone caption display"
```

---

### Task 2: Codex Pet Speech Bubble Styling & Layout Fix (TDD)

**Files:**
- Modify: `frontend/src/components/Kiosk/Pet/CodexPetSpeechBubble.tsx:80-137`
- Create: `frontend/src/components/Kiosk/Pet/CodexPetSpeechBubble.test.tsx`

**Interfaces:**
- Consumes: `formatSpeechText(text?: string, maxChars?: number): string`
- Produces: `<CodexPetSpeechBubble text={...} voiceStatus={...} maxChars={90} ... />`

- [ ] **Step 1: Write failing test in `CodexPetSpeechBubble.test.tsx`**

Create `frontend/src/components/Kiosk/Pet/CodexPetSpeechBubble.test.tsx`:
```tsx
import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CodexPetSpeechBubble, formatSpeechText } from './CodexPetSpeechBubble';

describe('formatSpeechText', () => {
  it('truncates text beyond maxChars with ellipsis', () => {
    expect(formatSpeechText('Ngắn', 90)).toBe('Ngắn');
    expect(formatSpeechText('A'.repeat(100), 90)).toBe('A'.repeat(87) + '...');
  });

  it('returns empty string for empty or undefined input', () => {
    expect(formatSpeechText('')).toBe('');
    expect(formatSpeechText(undefined)).toBe('');
  });
});

describe('CodexPetSpeechBubble component', () => {
  it('renders typing indicator when speaking without text', () => {
    render(<CodexPetSpeechBubble voiceStatus="speaking" text="" />);
    expect(screen.getByTestId('speech-bubble-typing')).toBeDefined();
  });

  it('renders speech text with proper wrapping container classes', () => {
    render(<CodexPetSpeechBubble voiceStatus="speaking" text="Chào bạn nhé!" />);
    const card = screen.getByTestId('speech-bubble-text').parentElement;
    expect(card?.className).toContain('w-max');
    expect(card?.className).toContain('min-w-');
    expect(card?.className).toContain('break-words');
    expect(screen.getByText('Chào bạn nhé!')).toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
npm --prefix /home/robber/Work/jarvis/OpenJarvis/frontend run test -- src/components/Kiosk/Pet/CodexPetSpeechBubble.test.tsx
```
Expected: FAIL due to missing `w-max` class in card.

- [ ] **Step 3: Update `CodexPetSpeechBubble.tsx` styling classes**

In `frontend/src/components/Kiosk/Pet/CodexPetSpeechBubble.tsx`:
Update default `maxChars = 90` in `CodexPetSpeechBubbleProps` and function signature.
Update the speech bubble card `div` (around line 97):
```tsx
      {/* Speech bubble card */}
      <div
        className="relative w-max min-w-[160px] max-w-[220px] sm:max-w-[280px] px-3.5 py-2 rounded-xl text-xs font-medium leading-snug shadow-xl backdrop-blur-md whitespace-normal break-words"
        style={{
          background: 'rgba(20, 20, 30, 0.88)',
          border: '1px solid rgba(255, 255, 255, 0.15)',
          color: '#ffffff',
          boxShadow: '0 8px 24px -4px rgba(0, 0, 0, 0.5), 0 0 12px rgba(0, 242, 254, 0.15)',
        }}
      >
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
npm --prefix /home/robber/Work/jarvis/OpenJarvis/frontend run test -- src/components/Kiosk/Pet/CodexPetSpeechBubble.test.tsx
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/robber/Work/jarvis/OpenJarvis
git add frontend/src/components/Kiosk/Pet/CodexPetSpeechBubble.tsx frontend/src/components/Kiosk/Pet/CodexPetSpeechBubble.test.tsx
git commit -m "fix(kiosk/pet): widen speech bubble card and prevent word squishing"
```

---

### Task 3: Floating Codex Pet Active Segment Teaser

**Files:**
- Modify: `frontend/src/components/Kiosk/Pet/FloatingCodexPet.tsx:140-180`
- Test: `frontend/src/components/Kiosk/Pet/FloatingCodexPet.test.tsx`

**Interfaces:**
- Consumes: `splitCaptionSegments` from `@/components/Chat/voiceTurnRows`
- Produces: `effectiveSpeechText` containing only the latest spoken sentence segment when falling back to `assistantCaptionText`.

- [ ] **Step 1: Write test for segment teaser extraction in `FloatingCodexPet.test.tsx`**

Create `frontend/src/components/Kiosk/Pet/FloatingCodexPet.test.tsx`:
```tsx
import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FloatingCodexPet } from './FloatingCodexPet';

describe('FloatingCodexPet speech teaser', () => {
  it('extracts latest sentence segment when assistantCaptionText has multiple sentences', () => {
    render(
      <FloatingCodexPet
        voiceStatus="speaking"
        assistantCaptionText="Xin chào bạn. Tôi đang chuẩn bị đơn hàng cho bạn nhé."
        petType="sprite"
      />
    );
    expect(screen.getByText('Tôi đang chuẩn bị đơn hàng cho bạn nhé.')).toBeDefined();
    expect(screen.queryByText('Xin chào bạn.')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
npm --prefix /home/robber/Work/jarvis/OpenJarvis/frontend run test -- src/components/Kiosk/Pet/FloatingCodexPet.test.tsx
```
Expected: FAIL because whole text is rendered.

- [ ] **Step 3: Update `FloatingCodexPet.tsx`**

In `frontend/src/components/Kiosk/Pet/FloatingCodexPet.tsx`:
Import `splitCaptionSegments` from `@/components/Chat/voiceTurnRows`.
Compute `effectiveSpeechText`:
```tsx
  const effectiveSpeechText = useMemo(() => {
    if (speechText) return speechText;
    if (!assistantCaptionText) return undefined;
    const segments = splitCaptionSegments(assistantCaptionText);
    return segments.length > 0 ? segments[segments.length - 1] : assistantCaptionText;
  }, [speechText, assistantCaptionText]);
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
npm --prefix /home/robber/Work/jarvis/OpenJarvis/frontend run test -- src/components/Kiosk/Pet/FloatingCodexPet.test.tsx
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/robber/Work/jarvis/OpenJarvis
git add frontend/src/components/Kiosk/Pet/FloatingCodexPet.tsx frontend/src/components/Kiosk/Pet/FloatingCodexPet.test.tsx
git commit -m "feat(kiosk/pet): display active sentence teaser in pet speech bubble"
```

---

### Task 4: Dynamic Caption Hold & Fade Lifecycle in `usePipecatVoiceMode`

**Files:**
- Modify: `frontend/src/hooks/usePipecatVoiceMode.ts:320-380`
- Test: `frontend/src/hooks/usePipecatVoiceMode.test.ts`

**Interfaces:**
- Produces in hook return: `assistantCaptionFading: boolean`.
- Lifecycle:
  - `BotStoppedSpeaking`: keeps `assistantCaptionText`, schedules fade after `voiceCaptionHoldMs(captionText)`, schedules clearing 400ms after fade starts.
  - `UserStartedSpeaking` / `end()`: cancels all timers, clears `assistantCaptionText` immediately, resets `assistantCaptionFading`.

- [ ] **Step 1: Add unit test in `usePipecatVoiceMode.test.ts`**

Add tests for hold estimation and schedule helpers:
```typescript
import { voiceCaptionHoldMs } from '@/components/Chat/voiceTurnRows';

describe('caption hold duration calculation', () => {
  it('keeps caption for proportional duration', () => {
    expect(voiceCaptionHoldMs('Chào bạn')).toBeGreaterThanOrEqual(900);
    expect(voiceCaptionHoldMs('Một câu văn bản dài hơn đáng kể cho khách đọc.')).toBeGreaterThan(1500);
  });
});
```

- [ ] **Step 2: Update `usePipecatVoiceMode.ts`**

1. Import `voiceCaptionHoldMs` from `@/components/Chat/voiceTurnRows`.
2. Add state and refs:
```typescript
  const [assistantCaptionFading, setAssistantCaptionFading] = useState(false);
  const captionHoldTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const captionFadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearCaptionTimers = useCallback(() => {
    if (captionHoldTimerRef.current) {
      clearTimeout(captionHoldTimerRef.current);
      captionHoldTimerRef.current = null;
    }
    if (captionFadeTimerRef.current) {
      clearTimeout(captionFadeTimerRef.current);
      captionFadeTimerRef.current = null;
    }
    setAssistantCaptionFading(false);
  }, []);
```
3. Update `UserStartedSpeaking`:
```typescript
    client.on(RTVIEvent.UserStartedSpeaking, () => {
      setStatus('listening');
      setActivityDetail(null);
      clearCaptionTimers();
      captionRef.current = '';
      setAssistantCaptionText('');
    });
```
4. Update `BotStartedSpeaking`:
```typescript
    client.on(RTVIEvent.BotStartedSpeaking, () => {
      setStatus('speaking');
      setActivityDetail(null);
      clearCaptionTimers();
    });
```
5. Update `BotStoppedSpeaking`:
```typescript
    client.on(RTVIEvent.BotStoppedSpeaking, () => {
      setStatus('listening');
      setActivityDetail(null);
      const finishedText = captionRef.current;
      const { message, nextCaption } = botStoppedSpeaking(finishedText);
      captionRef.current = nextCaption;
      if (message) onTurnRef.current?.(message);

      // Graceful hold and fade-out
      clearCaptionTimers();
      if (finishedText.trim()) {
        const holdMs = voiceCaptionHoldMs(finishedText);
        captionHoldTimerRef.current = setTimeout(() => {
          setAssistantCaptionFading(true);
          captionFadeTimerRef.current = setTimeout(() => {
            setAssistantCaptionText('');
            setAssistantCaptionFading(false);
          }, 400);
        }, holdMs);
      } else {
        setAssistantCaptionText('');
      }
    });
```
6. Update `end`:
```typescript
    clearCaptionTimers();
    setAssistantCaptionText('');
```
7. Expose `assistantCaptionFading` in returned object.

- [ ] **Step 3: Run tests to verify**

Run:
```bash
npm --prefix /home/robber/Work/jarvis/OpenJarvis/frontend run test -- src/hooks/usePipecatVoiceMode.test.ts
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/robber/Work/jarvis/OpenJarvis
git add frontend/src/hooks/usePipecatVoiceMode.ts frontend/src/hooks/usePipecatVoiceMode.test.ts
git commit -m "feat(voice): implement dynamic post-speech caption hold and fade-out"
```

---

### Task 5: Bottom Caption Dual-Opacity & Transition in `KioskPage.tsx`

**Files:**
- Modify: `frontend/src/pages/KioskPage.tsx:168-185`

**Interfaces:**
- Consumes: `partitionCaptionSegments` from `@/components/Chat/voiceTurnRows`
- Consumes: `voice.assistantCaptionFading` from `usePipecatVoiceMode`

- [ ] **Step 1: Update `KioskPage.tsx`**

Import `partitionCaptionSegments` from `@/components/Chat/voiceTurnRows`.
In the bottom captions area (lines 168-185):
```tsx
      {kioskState === 'active' && (
        <div className="absolute inset-x-0 bottom-0 z-20 flex flex-col items-center gap-3 px-4 pb-8 pointer-events-none">
          {settings.showCaptions && (
            <div className="w-full max-w-2xl flex flex-col items-center gap-2 text-center">
              {rows.filter((row) => row.role !== 'error').map((row) => {
                if (row.role === 'assistant') {
                  const { completedText, activeText } = partitionCaptionSegments(row.text);
                  return (
                    <div
                      key="assistant-caption"
                      className={`px-5 py-2.5 rounded-2xl bg-black/40 backdrop-blur-md border border-white/10 shadow-lg text-[16px] leading-relaxed max-w-2xl transition-opacity duration-400 ease-out ${
                        voice.assistantCaptionFading ? 'opacity-0' : 'opacity-100'
                      }`}
                    >
                      {completedText && (
                        <span className="opacity-70 text-white/70">{completedText} </span>
                      )}
                      <span className="opacity-100 text-white font-medium drop-shadow-sm">
                        {activeText}
                      </span>
                    </div>
                  );
                }
                return (
                  <p
                    key={row.role}
                    className="text-[13px] leading-snug text-[var(--color-text-tertiary)]"
                  >
                    {row.text}
                  </p>
                );
              })}
            </div>
          )}
        </div>
      )}
```

- [ ] **Step 2: Run test suite to verify no regressions**

Run:
```bash
npm --prefix /home/robber/Work/jarvis/OpenJarvis/frontend run test
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/robber/Work/jarvis/OpenJarvis
git add frontend/src/pages/KioskPage.tsx
git commit -m "feat(kiosk): render dual-tone reading guide and glass pill for bottom captions"
```

---

### Task 6: Full Verification & TypeScript Check

**Files:**
- All touched files

- [ ] **Step 1: Run TypeScript compiler check**

Run:
```bash
npx --prefix /home/robber/Work/jarvis/OpenJarvis/frontend tsc -b
```
Expected: Exit code 0, 0 errors.

- [ ] **Step 2: Run all frontend unit tests**

Run:
```bash
npm --prefix /home/robber/Work/jarvis/OpenJarvis/frontend run test
```
Expected: All test suites pass.

- [ ] **Step 3: Inspect git diff**

Run:
```bash
cd /home/robber/Work/jarvis/OpenJarvis && git diff HEAD~5..HEAD --stat
```
Expected: Clean, surgical diff across only the intended frontend files.
