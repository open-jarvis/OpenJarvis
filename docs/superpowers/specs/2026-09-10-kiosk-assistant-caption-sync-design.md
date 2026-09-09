# Kiosk Assistant Voice Caption Synchronization & Speech Bubble Redesign

## 1. Overview & Goal
In Kiosk Voice Mode (`feat/voice-mode-computer`), this design enhances the assistant's spoken text presentation to achieve natural, comfortable visual synchronization with the TTS audio stream. Customers can effortlessly listen and read along simultaneously.

### Key Objectives
1. **Dynamic Streaming with Active Tail Highlight (Bottom Caption)**: Text accumulates chunk-by-chunk as TTS streams in. The active sentence/tail chunk displays at 100% white with high contrast, while preceding completed sentences dim slightly (70% opacity) to guide the reader's eye.
2. **Graceful Post-Speech Hold & Fade-out**: Replace abrupt instantaneous caption clearing on `BotStoppedSpeaking` with a dynamic hold period (proportional to text length via `voiceCaptionHoldMs`: 1.5s – 3.5s) followed by a 400ms CSS fade-out. The caption clears immediately if the customer begins speaking (`UserStartedSpeaking`).
3. **Mascot Speech Bubble Layout Fix**: Resolve the squished speech bubble layout bug on the Codex Pet (where missing `w-max` / `min-w` collapsed the container down to ~50px, wrapping each word onto a single line).
4. **Clean Presentation Separation**:
   - **Codex Pet Bubble**: Displays a concise teaser/active sentence (`maxChars = 90`) and thinking/typing dots.
   - **Bottom Caption**: Primary readable transcript area with dual-tone reading guide.

### Scope Boundaries (Strict Frontend Only)
- **Included**: `frontend/src/hooks/usePipecatVoiceMode.ts`, `frontend/src/components/Chat/voiceTurnRows.ts`, `frontend/src/components/Chat/voiceTurnRows.test.ts`, `frontend/src/components/Kiosk/Pet/CodexPetSpeechBubble.tsx`, `frontend/src/components/Kiosk/Pet/FloatingCodexPet.tsx`, `frontend/src/pages/KioskPage.tsx`.
- **Excluded**: No backend changes, no Pipecat pipeline changes, no STT/TTS provider changes, no WebRTC/WebSocket protocol changes, no agent logic modifications.

---

## 2. Architecture & Data Flow

```text
Pipecat Client (RTVI Events)
   │
   ├─► RTVIEvent.BotStartedSpeaking
   │      └─ Voice status: 'speaking'. Clears any lingering fade/hold timeout.
   │
   ├─► RTVIEvent.BotTtsText({ text })
   │      ├─ Accumulates full raw caption in state / ref.
   │      ├─ Bottom Caption: splits into completed sentences (70% opacity) + active tail (100% opacity).
   │      └─ Pet Bubble: extracts current active sentence (slice(-1) via splitCaptionSegments, maxChars ~90).
   │
   ├─► RTVIEvent.BotStoppedSpeaking
   │      ├─ Calculates hold duration: `holdMs = voiceCaptionHoldMs(captionText)` (1.5s - 3.5s).
   │      ├─ Keeps caption visible during hold window.
   │      ├─ Triggers smooth CSS fade-out (400ms duration).
   │      └─ On fade completion: clears caption state and DOM cleanly.
   │
   └─► RTVIEvent.UserStartedSpeaking
          └─ Customer begins speaking: aborts hold/fade timer immediately, clears assistant caption to yield screen to customer transcript.
```

---

## 3. Component Details & File Modifications

### 3.1 `frontend/src/components/Chat/voiceTurnRows.ts` & `voiceTurnRows.test.ts`
- **Existing Helpers**:
  - `splitCaptionSegments(text: string): string[]`: splits on sentence terminators (`[.!?…]`).
  - `voiceCaptionHoldMs(text: string): number`: scales hold duration (`Math.min(5000, Math.max(900, Math.round(text.length * 65)))`).
- **New Helper**:
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
- **Tests in `voiceTurnRows.test.ts`**:
  - Test single sentence chunk returns empty `completedText` and full `activeText`.
  - Test multiple sentences partition correctly without losing punctuation or whitespace.
  - Test `voiceCaptionHoldMs` bounds.

### 3.2 `frontend/src/components/Kiosk/Pet/CodexPetSpeechBubble.tsx`
- **Bug Fix**:
  - Add `w-max min-w-[160px] max-w-[280px]` and `whitespace-normal break-words` to the bubble container card.
  - Set default `maxChars = 90`.
  - Preserve the downward speech tail pointer centered/aligned with the pet head.
- **Typing Indicator**:
  - Render jumping dots during `processing` or `inference` prior to first spoken chunk.

### 3.3 `frontend/src/components/Kiosk/Pet/FloatingCodexPet.tsx`
- Pass only the current active sentence to `PetRenderer`:
  ```typescript
  const petSpeechText = useMemo(() => {
    if (speechText) return speechText;
    if (!assistantCaptionText) return '';
    const segments = splitCaptionSegments(assistantCaptionText);
    return segments[segments.length - 1] || assistantCaptionText;
  }, [speechText, assistantCaptionText]);
  ```

### 3.4 `frontend/src/hooks/usePipecatVoiceMode.ts`
- Add caption hold and fade state:
  ```typescript
  const [captionFading, setCaptionFading] = useState(false);
  const captionHoldTimerRef = useRef<NodeJS.Timeout | null>(null);
  const captionFadeTimerRef = useRef<NodeJS.Timeout | null>(null);
  ```
- When `BotStoppedSpeaking`:
  - Compute hold duration with `voiceCaptionHoldMs(captionRef.current)`.
  - Set timer to trigger `setCaptionFading(true)` after `holdMs`.
  - Set follow-up timer (400ms) to clear `assistantCaptionText` and reset `captionFading(false)`.
- When `UserStartedSpeaking` or `end()` or unmount:
  - Clear both timers, reset `captionFading` and `assistantCaptionText`.

### 3.5 `frontend/src/pages/KioskPage.tsx`
- Refine the bottom caption rendering:
  - If `row.role === 'assistant'`, use `partitionCaptionSegments(row.text)`:
    - `<span className="opacity-70 text-white/70">{completedText} </span>`
    - `<span className="opacity-100 text-white font-medium">{activeText}</span>`
  - Wrap in a stylish glass pill:
    `bg-black/40 backdrop-blur-md px-5 py-2.5 rounded-2xl border border-white/10 shadow-lg`
  - Apply transition class:
    `transition-opacity duration-400 ease-out ${captionFading ? 'opacity-0' : 'opacity-100'}`

---

## 4. Non-Functional Requirements
- **60 FPS Performance**: Pure CSS transitions (`opacity`), zero layout thrashing, zero heavy canvas re-renders.
- **Responsive Layout**: Adapts gracefully across portrait/landscape kiosk screens and standard desktop resolutions.
- **Robust Cleanup**: All timeouts (`captionHoldTimerRef`, `captionFadeTimerRef`) are properly destroyed on component unmount and session reset to prevent memory leaks or dangling setState calls.

---

## 5. Verification & Acceptance Criteria

### Automated Testing
- `npm run test` (vitest): All unit tests in `voiceTurnRows.test.ts` pass 100%.
- `npm run typecheck`: Zero TypeScript compile errors.

### Manual / Visual Verification
1. **TTS Synchronization**: Text streams in smoothly without layout jitter; completed sentences dim to 70%, active sentence shines at 100%.
2. **Pet Speech Bubble**: Bubble expands to comfortable width (160–280px), single words no longer wrap individually.
3. **Graceful Hold**: When TTS finishes, text remains on screen for ~1.5s–3.5s, then fades out smoothly over 400ms.
4. **Immediate Interrupt**: If the customer starts speaking during the hold period, the assistant caption disappears immediately.
