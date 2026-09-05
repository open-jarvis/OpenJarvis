"""JARVIS COMMAND CENTER - desktop GUI.

Maps onto the command-center architecture:
  GUI          -> this file (customtkinter)
  JARVIS CORE  -> jarvis_core.JarvisCore (HTTP client for the OpenJarvis
                  backend's router/providers/memory/telemetry on :8000)
  VOICE CORE   -> jarvis_voice.VoiceCore (local STT via faster-whisper,
                  local TTS via pyttsx3+sounddevice, push-to-talk - no
                  wake-word listening yet)
Providers (Qwen/Claude/Gemini) -> jarvis_providers.py
"""

import os
import shlex
import shutil
import subprocess
import threading

import customtkinter as ctk

from jarvis_core import JarvisCore
from jarvis_providers import ProviderNotConfigured, default_providers
from jarvis_voice import VoiceCore

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# terminal-jarvis lives in ~/.cargo/bin, which may not be on this process's
# PATH depending on how the GUI was launched.
TERMINAL_JARVIS = shutil.which("terminal-jarvis") or os.path.expanduser(
    "~/.cargo/bin/terminal-jarvis.exe"
)


class JarvisGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("J.A.R.V.I.S. Command Center")
        self.geometry("860x680")

        self.core = JarvisCore()
        self.providers = default_providers(self.core)
        self.voice = VoiceCore()
        self.history = []

        # Voice state machine: "idle" | "listening" | "speaking".
        # Drives what Ctrl+Space / the mic button do next.
        self.voice_state = "idle"

        self._build_ui()
        self.bind_all("<Control-space>", self.on_voice_trigger)
        self.after(500, lambda: self.log_message("System: Initializing core systems..."))
        self.after(1500, lambda: self.log_message("J.A.R.V.I.S: Awaiting your command, Boss."))

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_ui(self):
        title_label = ctk.CTkLabel(
            self, text="J.A.R.V.I.S. ONLINE", font=("Helvetica", 20, "bold"), text_color="#00d2ff"
        )
        title_label.pack(pady=(15, 5))

        self.tabs = ctk.CTkTabview(self, width=820, height=600)
        self.tabs.pack(padx=15, pady=10, fill="both", expand=True)

        self._build_command_center(self.tabs.add("Command Center"))
        self._build_info_tab(self.tabs.add("Dashboard"), self.refresh_dashboard, "dashboard_box")
        self._build_info_tab(self.tabs.add("Agents"), self.refresh_agents, "agents_box")
        self._build_memory_tab(self.tabs.add("Memory"))
        self._build_info_tab(self.tabs.add("LLM Status"), self.refresh_models, "models_box")
        self._build_info_tab(
            self.tabs.add("System Monitor"), self.refresh_system_monitor, "monitor_box"
        )

    def _build_command_center(self, tab):
        self.text_area = ctk.CTkTextbox(tab, width=780, height=380, font=("Courier", 12))
        self.text_area.pack(pady=(10, 5), padx=10)

        controls = ctk.CTkFrame(tab, fg_color="transparent")
        controls.pack(fill="x", padx=10, pady=(0, 5))

        self.provider_var = ctk.StringVar(value="Qwen (local)")
        provider_menu = ctk.CTkOptionMenu(
            controls, values=list(self.providers.keys()), variable=self.provider_var, width=140
        )
        provider_menu.pack(side="left")

        self.speak_var = ctk.BooleanVar(value=False)
        speak_check = ctk.CTkCheckBox(controls, text="Speak replies", variable=self.speak_var)
        speak_check.pack(side="left", padx=10)

        self.stop_btn = ctk.CTkButton(
            controls, text="Stop", width=70, fg_color="#8b0000", command=self.on_stop_click
        )
        self.stop_btn.pack(side="right")

        self.mic_btn = ctk.CTkButton(
            controls, text="Speak", width=90, command=self.on_voice_trigger
        )
        self.mic_btn.pack(side="right", padx=10)

        input_row = ctk.CTkFrame(tab, fg_color="transparent")
        input_row.pack(fill="x", padx=10, pady=(0, 10))

        self.input_box = ctk.CTkEntry(
            input_row, placeholder_text="Type a command, or 'tj <cmd>' for terminal-jarvis..."
        )
        self.input_box.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.input_box.bind("<Return>", lambda event: self.send_command())

        self.send_btn = ctk.CTkButton(input_row, text="Execute", width=90, command=self.send_command)
        self.send_btn.pack(side="right")

    def _build_info_tab(self, tab, refresh_fn, box_attr):
        box = ctk.CTkTextbox(tab, width=780, height=480, font=("Courier", 12))
        box.pack(pady=10, padx=10, fill="both", expand=True)
        setattr(self, box_attr, box)

        refresh_btn = ctk.CTkButton(tab, text="Refresh", width=100, command=refresh_fn)
        refresh_btn.pack(pady=(0, 10))
        self.after(300, refresh_fn)

    def _build_memory_tab(self, tab):
        self.memory_box = ctk.CTkTextbox(tab, width=780, height=420, font=("Courier", 12))
        self.memory_box.pack(pady=10, padx=10, fill="both", expand=True)

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 10))

        self.memory_search_box = ctk.CTkEntry(row, placeholder_text="Search memory...")
        self.memory_search_box.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.memory_search_box.bind("<Return>", lambda event: self.search_memory())

        ctk.CTkButton(row, text="Search", width=90, command=self.search_memory).pack(side="right")
        ctk.CTkButton(row, text="Stats", width=90, command=self.refresh_memory).pack(
            side="right", padx=10
        )
        self.after(300, self.refresh_memory)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    def log_message(self, message):
        """Print into the Command Center textbox. Thread-safe."""
        self.after(0, lambda: (self.text_area.insert("end", f"{message}\n"), self.text_area.see("end")))

    def _set_box(self, box, text):
        """Replace an info-tab textbox's content. Thread-safe."""

        def update():
            box.delete("1.0", "end")
            box.insert("1.0", text)

        self.after(0, update)

    # ------------------------------------------------------------------
    # Command Center
    # ------------------------------------------------------------------
    def send_command(self):
        user_text = self.input_box.get()
        if user_text:
            self._submit(user_text)

    def _submit(self, user_text):
        self.log_message(f"You: {user_text}")
        self.input_box.delete(0, "end")
        self.send_btn.configure(state="disabled")

        # Messages prefixed with "tj " are routed to terminal-jarvis
        # (headless, since its TUI needs a real interactive terminal this
        # process doesn't have) instead of the chat backend.
        if user_text.strip().lower().startswith("tj "):
            args = user_text.strip()[3:].strip()
            threading.Thread(target=self.run_terminal_jarvis, args=(args,), daemon=True).start()
        else:
            threading.Thread(target=self.ask_jarvis, args=(user_text,), daemon=True).start()

    def ask_jarvis(self, user_text):
        """Send the conversation to the selected provider and print/speak its reply."""
        self.history.append({"role": "user", "content": user_text})
        try:
            provider = self.providers[self.provider_var.get()]
            reply = provider.chat(self.history)
            self.history.append({"role": "assistant", "content": reply})
            self.log_message(f"J.A.R.V.I.S: {reply}")
            if self.speak_var.get():
                threading.Thread(target=self._speak_worker, args=(reply,), daemon=True).start()
        except ProviderNotConfigured as exc:
            self.log_message(f"System: {exc}")
        except Exception as exc:
            self.log_message(f"System: Error contacting backend - {exc}")
        finally:
            self.after(0, lambda: self.send_btn.configure(state="normal"))

    def run_terminal_jarvis(self, args):
        """Run a headless terminal-jarvis command and print its output."""
        try:
            cmd = [TERMINAL_JARVIS, "--plain"] + shlex.split(args)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            output = (result.stdout or result.stderr or "(no output)").strip()
            self.log_message(f"terminal-jarvis:\n{output}")
        except FileNotFoundError:
            self.log_message(f"System: terminal-jarvis executable not found at {TERMINAL_JARVIS}")
        except subprocess.TimeoutExpired:
            self.log_message("System: terminal-jarvis command timed out after 60s")
        except Exception as exc:
            self.log_message(f"System: Error running terminal-jarvis - {exc}")
        finally:
            self.after(0, lambda: self.send_btn.configure(state="normal"))

    # ------------------------------------------------------------------
    # Voice
    # ------------------------------------------------------------------
    def on_voice_trigger(self, event=None):
        """Ctrl+Space or the mic button.

        Idle    -> start listening.
        Speaking -> interrupt playback immediately, then start listening
                    (natural conversational interruption - the user talking
                    over Jarvis means "stop and hear me now", not "queue up
                    after you finish").
        Listening -> already capturing input; ignore repeat triggers.
        """
        if self.voice_state == "listening":
            return
        if self.voice_state == "speaking":
            self.voice.stop_speaking()
            self.log_message("System: (interrupted)")
        self._start_listening()

    def _start_listening(self):
        self.voice_state = "listening"
        self.mic_btn.configure(state="disabled", text="Listening...")
        threading.Thread(target=self._record_worker, daemon=True).start()

    def _record_worker(self):
        try:
            text = self.voice.record_and_transcribe(seconds=5.0)
            if text:
                self.after(0, lambda: self._submit(text))
            else:
                self.log_message("System: Didn't catch anything.")
        except Exception as exc:
            self.log_message(f"System: Voice input error - {exc}")
        finally:
            self.voice_state = "idle"
            self.after(0, lambda: self.mic_btn.configure(state="normal", text="Speak"))

    def _speak_worker(self, text):
        self.voice_state = "speaking"
        self.after(0, lambda: self.mic_btn.configure(text="Interrupt"))
        try:
            self.voice.speak(text)
        finally:
            # Only reset to idle if nothing else (e.g. an interruption that
            # already moved us to "listening") has claimed the state since.
            if self.voice_state == "speaking":
                self.voice_state = "idle"
                self.after(0, lambda: self.mic_btn.configure(text="Speak"))

    def on_stop_click(self):
        self.voice.stop_speaking()
        if self.voice_state == "speaking":
            self.voice_state = "idle"
            self.mic_btn.configure(text="Speak")

    # ------------------------------------------------------------------
    # Dashboard / Agents / LLM Status / System Monitor (read-only panels)
    # ------------------------------------------------------------------
    def refresh_dashboard(self):
        threading.Thread(target=self._refresh_dashboard_worker, daemon=True).start()

    def _refresh_dashboard_worker(self):
        try:
            healthy = self.core.health()
            lines = [f"Backend:  {'ONLINE' if healthy else 'OFFLINE'} (http://localhost:8000)"]
            if healthy:
                info = self.core.info()
                lines += [
                    "",
                    f"Active model:  {info.get('model', '?')}",
                    f"Active agent:  {info.get('agent', '?')}",
                    f"Engine:        {info.get('engine', '?')}",
                ]
                savings = self.core.savings()
                lines += [
                    "",
                    "-- Session savings --------------------------------",
                    f"Total calls:            {savings.get('total_calls', 0)}",
                    f"Total tokens:           {savings.get('total_tokens', 0)}",
                    f"Local cost:             ${savings.get('local_cost', 0):.4f}",
                ]
                for p in savings.get("per_provider", []):
                    lines.append(
                        f"  vs {p.get('label', p.get('provider')):<18} "
                        f"would have cost ${p.get('total_cost', 0):.4f}"
                    )
            self._set_box(self.dashboard_box, "\n".join(lines))
        except Exception as exc:
            self._set_box(self.dashboard_box, f"Error fetching dashboard: {exc}")

    def refresh_agents(self):
        threading.Thread(target=self._refresh_agents_worker, daemon=True).start()

    def _refresh_agents_worker(self):
        lines = ["-- OpenJarvis agents (/v1/agents) -------------------"]
        try:
            for a in self.core.list_agents():
                tools = "tools" if a.get("accepts_tools") else "no-tools"
                lines.append(f"  {a['key']:<20} {a.get('class', ''):<24} [{tools}]")
        except Exception as exc:
            lines.append(f"  Error: {exc}")

        lines += ["", "-- terminal-jarvis harnesses -------------------------"]
        try:
            cmd = [TERMINAL_JARVIS, "--plain", "list"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            lines.append((result.stdout or result.stderr or "(no output)").strip())
        except Exception as exc:
            lines.append(f"  Error: {exc}")

        self._set_box(self.agents_box, "\n".join(lines))

    def refresh_models(self):
        threading.Thread(target=self._refresh_models_worker, daemon=True).start()

    def _refresh_models_worker(self):
        lines = ["-- Models available via the backend (/v1/models) ----"]
        try:
            for m in self.core.list_models():
                lines.append(f"  {m['id']}")
        except Exception as exc:
            lines.append(f"  Error: {exc}")
        lines += ["", "-- Providers configured in this GUI -----------------"]
        for name in self.providers:
            status = "ready" if name == "Qwen (local)" else "stub (needs API key + implementation)"
            lines.append(f"  {name:<15} {status}")
        self._set_box(self.models_box, "\n".join(lines))

    def refresh_system_monitor(self):
        threading.Thread(target=self._refresh_monitor_worker, daemon=True).start()

    def _refresh_monitor_worker(self):
        lines = ["-- Telemetry (/v1/telemetry/stats) ------------------"]
        try:
            stats = self.core.telemetry_stats()
            lines += [
                f"  Total requests:        {stats.get('total_requests', 0)}",
                f"  Total tokens:          {stats.get('total_tokens', 0)}",
                f"  Total latency (s):     {stats.get('total_latency', 0):.2f}",
                f"  Avg throughput (t/s):  {stats.get('avg_throughput_tok_per_sec', 0):.2f}",
            ]
        except Exception as exc:
            lines.append(f"  Error: {exc}")

        lines += ["", "-- Energy (/v1/telemetry/energy) --------------------"]
        try:
            energy = self.core.telemetry_energy()
            lines += [
                f"  Total energy (J):      {energy.get('total_energy_j', 0)}",
                f"  Avg power (W):         {energy.get('avg_power_w', 0)}",
                f"  CPU temp (C):          {energy.get('cpu_temp_c')}",
                f"  GPU temp (C):          {energy.get('gpu_temp_c')}",
            ]
        except Exception as exc:
            lines.append(f"  Error: {exc}")

        self._set_box(self.monitor_box, "\n".join(lines))

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------
    def refresh_memory(self):
        threading.Thread(target=self._refresh_memory_worker, daemon=True).start()

    def _refresh_memory_worker(self):
        try:
            stats = self.core.memory_stats()
            if "detail" in stats:
                text = f"Memory backend unavailable:\n\n{stats['detail']}"
            else:
                text = "\n".join(f"{k}: {v}" for k, v in stats.items())
        except Exception as exc:
            text = f"Error fetching memory stats: {exc}"
        self._set_box(self.memory_box, text)

    def search_memory(self):
        query = self.memory_search_box.get().strip()
        if not query:
            return
        threading.Thread(target=self._search_memory_worker, args=(query,), daemon=True).start()

    def _search_memory_worker(self, query):
        try:
            result = self.core.memory_search(query)
            if "detail" in result:
                text = f"Memory backend unavailable:\n\n{result['detail']}"
            else:
                text = "\n".join(str(item) for item in result.get("results", result))
        except Exception as exc:
            text = f"Error searching memory: {exc}"
        self._set_box(self.memory_box, f"Search: {query}\n\n{text}")


if __name__ == "__main__":
    app = JarvisGUI()
    app.mainloop()
