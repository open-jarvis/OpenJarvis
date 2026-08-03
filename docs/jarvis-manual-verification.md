# JARVIS manual verification runbook

This checklist is for a later, deliberate test session. The implementation
change that introduced it did **not** run an installer, build, warmup, test
suite, paid API call or real external action.

## Voice

1. Save `ELEVENLABS_API_KEY` in the desktop keyring and confirm that the UI
   shows only configured status, never the value.
2. Load the account's real voice list, select a German-suitable voice, save the
   real voice ID and audition it.
3. Speak a short answer and verify `eleven_flash_v2_5`, German language and the
   displayed actual provider.
4. Remove the key or disconnect the network and verify visible
   ElevenLabs → Chatterbox fallback for only the pending chunk.
5. Make Chatterbox unavailable and verify visible Piper emergency labelling.
6. Lower the per-response/monthly limit and verify the limit warning, local
   fallback and unchanged counter on an identical cache hit.
7. Force a provider and full-chain chunk failure; verify the warning and skipped
   section count.
8. Test Stop during HTTP synthesis, local synthesis, prefetch and playback.
9. Test microphone-button and Space barge-in while speaking.
10. Test noise calibration, speech detection, 900 ms post-speech silence,
    manual stop and the maximum recording timer. Confirm exactly one transcript
    and one submitted message.

## UI

1. Confirm no face, portrait, eyes or mouth appear in Talk or Text mode.
2. Resize from a small normal window through maximized mode and test Windows DPI
   scales used on the machine; controls and the lower star field must remain
   visible.
3. Verify real microphone level affects Listening particles, Processing uses a
   distinct convergence/swirl, and Speaking follows actual audio playback.
4. Enable/disable the processing bass tone; verify fade-in/out and immediate
   stop on answer, error, Stop and barge-in.
5. Enable reduced motion and verify lower particle/framerate work while state
   text remains understandable.
6. Break LLM, TTS and STT separately; verify concrete visible errors and a still
   usable Text mode.

## Desktop

1. Add an existing `.exe` plus a unique title substring in Settings and grant
   persistent Observe/Interact access. Restart the app and verify persistence.
2. Verify monitor enumeration (including negative coordinates), window list,
   active window, process identity, bounds and DPI. Inspect a modern WPF/WinUI
   application and confirm Settings reports `Windows UI Automation`; separately
   confirm the visible classic-Win32 fallback.
3. Verify focus, minimize/maximize/restore, move/resize, launch-if-absent,
   semantic text, normal click, clipboard, allowlisted hotkey and scroll.
4. Capture a window/region artifact and inspect its bounded path and hash.
5. Verify every mutation observes its postcondition. Force focus loss, window
   movement, a modal dialog and process restart; success must not be claimed.
6. Try the visual click only after a current screenshot; verify current focus,
   bounds, DPI, before/after artifacts and Level-3 allow-once approval.
7. Verify labels suggesting send/upload/publish/delete/purchase are rejected by
   the normal click tool and require the sensitive click approval.
8. Test multiple monitors, slow applications and Global Stop.
9. Open UAC Secure Desktop or lock the session and confirm a visible refusal.
   Do not attempt to bypass it. Confirm protected password fields are refused.

## MCP

1. Add one known server through Settings using Streamable HTTP, and one local
   stdio server using an absolute command path. Store any token in the desktop
   keyring, not server JSON.
2. Reconnect, inspect server health, last connection/error, namespaced tools and
   Include/Exclude filtering.
3. Mark one tool read-only, one preparation/write with approval, and one
   blocked. Confirm the model cannot choose or lower these classifications.
4. Execute a read tool from the canonical chat and inspect the Tool Proposal →
   ToolActionService → policy → MCP call → verification → task/trace sequence.
5. Approve a write tool once and confirm it executes only after the approval.
   Where the service exposes a read-back operation, observe the external state;
   otherwise treat the MCP success envelope as an acknowledgement rather than
   independent proof of the external effect.
6. Confirm returned content is labelled as untrusted MCP data and cannot become
   a system instruction.
7. Break one server while another is healthy. Confirm the healthy server and
   Text mode remain usable and the failed server has a safe visible error.
8. Test reconnect, HTTP/stdio timeout and Global Stop during a call.

## Static and automated commands for the owner

Choose commands appropriate to the installed environment. At minimum, run the
targeted speech/server/desktop/MCP tests, frontend component tests, Python lint,
TypeScript type checking and the desktop release build before calling the
feature verified. Run the voice setup and warmup separately, then perform the
manual checks above. Paid voice generation and real external writes must be
explicit, controlled test actions.
