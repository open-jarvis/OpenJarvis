"""
Jarvis Local Server
- Loest CORS-Problem mit Ollama
- Brave Search Integration
- Echtzeit-Voice via WebSocket
Starten: uv run python jarvis_server.py
Dann: http://localhost:7777
"""

import asyncio
import base64
import json
import logging
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading
import urllib.request
import urllib.parse

from jarvis_secrets import load_secret
from jarvis_transcription import transcribe_audio

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
tts_executor = ThreadPoolExecutor(max_workers=3)

BRAVE_API_KEY = load_secret(
    "brave_api_key",
    env_names=("BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY"),
)
ELEVENLABS_KEY = load_secret(
    "elevenlabs_api_key",
    env_names=("ELEVENLABS_API_KEY",),
)
# Daniel — klare britische Stimme, exzellente Deutsch-Aussprache mit multilingual_v2
ELEVENLABS_VOICE = load_secret(
    "elevenlabs_voice_id",
    env_names=("ELEVENLABS_VOICE_ID", "ELEVENLABS_VOICE"),
    default="onwK4e9ZLuTAKqWW03F9",
)

# Lange Texte: nach ~700 Zeichen pausieren und "Soll ich weiterlesen?" fragen
READ_LIMIT = 700
OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen3:8b"
PORT  = 7777

SYSTEM_PROMPT = """Du bist Clark, der persoenliche KI-Assistent von Arsenij Ergadt.
Du bist wie ein diskreter britischer Butler, Siri und ein smarter Mitarbeiter in einem.

IDENTITAET:
- Du heisst Clark. Du bist Clark.
- Der Nutzer heisst Arsenij (ausgesprochen: Ar-SEN-ij, russischer Name).
- Nenne ihn bei seinem Namen wenn es natuerlich passt.

KOMMUNIKATION:
- Antworte immer in der Sprache in der Arsenij schreibt/spricht (Deutsch oder Englisch).
- Sei direkt, kurz und klar — besonders bei Sprach-Antworten (max 2-3 Saetze wenn moeglich).
- Sprich ruhig, hoeflich, praezise — wie ein kultivierter britischer Butler.
- Kein unnötiges Gerede, komm direkt zum Punkt.
- Du bist Arsenijs lokaler, privater Assistent — keine Daten verlassen seinen PC.

FAEHIGKEITEN (Skils die Clark aktiv nutzen kann):
1. Web-Suche — Brave Search fuer aktuelle Infos, News, Preise, Fakten.
2. Datum & Uhrzeit — wird immer automatisch mitgegeben, du kennst die aktuelle Zeit.
3. Sprache & Text — Texte schreiben, uebersetzen, zusammenfassen, erklaeren.
4. Planung & Organisation — Aufgaben priorisieren, Plaene entwerfen, strukturieren.
5. Recherche & Analyse — Informationen suchen, vergleichen und aufbereiten.
6. Coding-Hilfe — Code schreiben, reviewen, debuggen in allen Sprachen.
7. Mathematik & Logik — Berechnungen, Problemloesungen, logische Ableitungen.
8. Kreatives Schreiben — Texte, E-Mails, Briefe, Social-Media-Posts verfassen.
9. Lange Texte vorlesen — Bei langen Antworten liest Clark den ersten Teil und fragt
   ob er weiterlesen soll. Arsenij antwortet dann einfach "ja" oder "weiter".

WICHTIG ZUR WEB-SUCHE:
Wenn du Web-Suchergebnisse bekommst (markiert mit "Aktuelle Web-Ergebnisse:"),
MUSST du diese als Grundlage deiner Antwort verwenden.
Zitiere konkrete Fakten. Sag "laut [Quelle]" statt "laut meinen Informationen".
Verlasse dich bei aktuellen Themen IMMER auf die Suchergebnisse."""


def run_agent(message: str, history: list) -> str:
    """ReAct-Agent mit Brave Search Tool — Jarvis entscheidet selbst wann er sucht."""
    try:
        from openjarvis.core.config import load_config
        from openjarvis.engine import get_engine
        from openjarvis.agents.native_react import NativeReActAgent
        from openjarvis.tools._stubs import BaseTool, ToolSpec
        from openjarvis.core.types import ToolResult

        # Brave Search Tool
        class BraveSearchTool(BaseTool):
            tool_id = "web_search"
            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="web_search",
                    description="Search the web for current, real-time information. Use for news, prices, people, events, or anything that may have changed recently.",
                    parameters={"type":"object","properties":{"query":{"type":"string","description":"Search query"}},"required":["query"]},
                    category="search",
                )
            def execute(self, **params) -> ToolResult:
                return ToolResult(tool_name="web_search", content=brave_search(params.get("query","")), success=True)

        # Datum & Uhrzeit Tool
        class DateTimeTool(BaseTool):
            tool_id = "get_datetime"
            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="get_datetime",
                    description="Get the current date, time, weekday and timezone. Use when asked about current time or date.",
                    parameters={"type":"object","properties":{}},
                    category="utility",
                )
            def execute(self, **params) -> ToolResult:
                import datetime as _dt
                now = _dt.datetime.now()
                result = (f"Aktuelle Zeit: {now.strftime('%H:%M:%S')} Uhr\n"
                          f"Datum: {now.strftime('%A, %d. %B %Y')}")
                return ToolResult(tool_name="get_datetime", content=result, success=True)

        # Taschenrechner Tool
        class CalculatorTool(BaseTool):
            tool_id = "calculator"
            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="calculator",
                    description="Evaluate a mathematical expression precisely. Use for calculations.",
                    parameters={"type":"object","properties":{"expression":{"type":"string","description":"Math expression, e.g. '(15 * 3) / 2 + 10'"}},"required":["expression"]},
                    category="utility",
                )
            def execute(self, **params) -> ToolResult:
                try:
                    expr = params.get("expression", "")
                    safe = {k: v for k,v in __builtins__.items() if k in ("abs","round","min","max","sum","pow")} if isinstance(__builtins__, dict) else {}
                    result = eval(expr, {"__builtins__": safe})
                    return ToolResult(tool_name="calculator", content=f"{expr} = {result}", success=True)
                except Exception as e:
                    return ToolResult(tool_name="calculator", content=f"Fehler: {e}", success=False)

        # System-Info Tool
        class SystemInfoTool(BaseTool):
            tool_id = "system_info"
            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="system_info",
                    description="Get current system information: CPU usage, RAM usage, disk space. Use when asked about PC performance or resources.",
                    parameters={"type":"object","properties":{}},
                    category="utility",
                )
            def execute(self, **params) -> ToolResult:
                try:
                    import psutil
                    cpu = psutil.cpu_percent(interval=0.5)
                    ram = psutil.virtual_memory()
                    disk = psutil.disk_usage("/")
                    result = (f"CPU: {cpu}%\n"
                              f"RAM: {ram.used//1024//1024} MB / {ram.total//1024//1024} MB ({ram.percent}%)\n"
                              f"Disk C: {disk.used//1024//1024//1024} GB / {disk.total//1024//1024//1024} GB frei: {disk.free//1024//1024//1024} GB")
                    return ToolResult(tool_name="system_info", content=result, success=True)
                except Exception as e:
                    return ToolResult(tool_name="system_info", content=f"System-Info nicht verfuegbar: {e}", success=False)

        config = load_config()
        engine = get_engine(config)

        agent = NativeReActAgent(
            engine=engine,
            model=MODEL,
            tools=[BraveSearchTool(), DateTimeTool(), CalculatorTool(), SystemInfoTool()],
            max_turns=6,
            temperature=0.7,
        )

        # History als Kontext zusammenfassen
        context = ""
        if history:
            recent = history[-6:]
            context = "\n".join(
                f"{'Arsenij' if m['role']=='user' else 'Clark'}: {m['content']}"
                for m in recent
            )
            context = f"Bisheriger Gesprächsverlauf:\n{context}\n\n"

        full_prompt = f"{SYSTEM_PROMPT}\n\n{context}Arsenij fragt: {message}"

        from openjarvis.agents._stubs import AgentContext
        ctx = AgentContext(objective=full_prompt, history=[])
        result = agent.run(ctx)
        return result.output or "Keine Antwort."

    except Exception as e:
        logger.warning(f"ReAct-Agent Fehler ({e}), nutze direktes Chat")
        return chat_with_jarvis_direct(message, history)


def chat_with_jarvis_direct(message: str, history: list) -> str:
    """Direktes Chat ohne Agent — Fallback."""
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        search_results = brave_search(message) if len(message) > 10 else ""
        if search_results and "fehlgeschlagen" not in search_results:
            messages.append({"role": "system", "content": f"Aktuelle Web-Ergebnisse:\n{search_results}"})
        for entry in history[-10:]:
            messages.append(entry)
        messages.append({"role": "user", "content": message})
        data = json.dumps({"model": MODEL, "messages": messages, "stream": False}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat", data=data,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())["message"]["content"]
    except Exception as e:
        return f"Fehler: {e}"


def brave_search(query: str, count: int = 5) -> str:
    """Brave Search API anfragen."""
    try:
        if not BRAVE_API_KEY:
            return "Web-Suche ist lokal noch nicht konfiguriert."
        params = urllib.parse.urlencode({
            "q": query,
            "count": count,
            "safesearch": "moderate",
            "search_lang": "de",
        })
        url = f"https://api.search.brave.com/res/v1/web/search?{params}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": BRAVE_API_KEY,
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            import gzip
            raw = resp.read()
            if resp.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            data = json.loads(raw)

        results = data.get("web", {}).get("results", [])
        if not results:
            return "Keine Suchergebnisse gefunden."

        lines = [f"Suchergebnisse fuer: {query}\n"]
        for i, r in enumerate(results[:5], 1):
            title = r.get("title", "")
            desc = r.get("description", "")
            url_r = r.get("url", "")
            lines.append(f"{i}. {title}\n   {desc}\n   Quelle: {url_r}\n")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Brave Search Fehler: {e}")
        return f"Suche fehlgeschlagen: {e}"


WEITERLESEN_AFFIRMATIVES = {
    "ja", "weiter", "yes", "continue", "klar", "okay", "ok", "bitte",
    "sure", "gerne", "mach weiter", "weiterlesen", "weiter lesen", "lesen",
    "ja bitte", "natürlich", "jo", "jep", "yep", "jaa", "ja gerne",
}

def is_weiterlesen_reply(message: str) -> bool:
    """Gibt True wenn die Nachricht eine Zustimmung zum Weiterlesen ist."""
    m = message.lower().strip().rstrip("!")
    return m in WEITERLESEN_AFFIRMATIVES or any(m.startswith(a+" ") for a in WEITERLESEN_AFFIRMATIVES)


def needs_search(message: str) -> bool:
    """Suche immer — außer bei simplen Fragen wie Mathe, Begrüßung, etc."""
    no_search = [
        "hallo", "hi", "hey", "danke", "bitte", "ok", "okay",
        "ja", "nein", "tschüss", "bye", "wie geht", "was machst",
    ]
    msg_lower = message.lower().strip()
    # Sehr kurze Begrüßungen/Antworten nicht suchen
    if len(msg_lower) < 8:
        return False
    if any(msg_lower.startswith(w) for w in no_search) and len(msg_lower) < 25:
        return False
    # Weiterlesen-Antworten nie suchen
    if is_weiterlesen_reply(message):
        return False
    # Reine Mathe-Ausdrücke nicht suchen
    if all(c in "0123456789+-*/().,= " for c in msg_lower):
        return False
    # Alles andere → suchen
    return True


def stream_ollama_tokens(messages: list):
    """Ollama Streaming — liefert Text-Token fuer Token."""
    data = json.dumps({
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.7}
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            for raw_line in resp:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    chunk = json.loads(raw_line)
                except Exception:
                    continue
                if chunk.get("done"):
                    break
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
    except Exception as e:
        logger.error(f"Ollama streaming Fehler: {e}")
        yield ""


def chat_with_jarvis(message: str, history: list, use_search: bool = True) -> str:
    """Nachricht an Jarvis schicken und Antwort bekommen."""
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Brave Search wenn noetig
        search_context = ""
        if use_search and needs_search(message):
            logger.info(f"Suche im Web: {message[:50]}")
            search_results = brave_search(message)
            search_context = f"\n\nAktuelle Web-Ergebnisse:\n{search_results}\n\nNutze diese Infos fuer deine Antwort."

        for entry in history[-12:]:
            messages.append(entry)

        user_content = message + search_context if search_context else message
        messages.append({"role": "user", "content": user_content})

        data = json.dumps({
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7}
        }).encode()

        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
        return result["message"]["content"]

    except Exception as e:
        logger.error(f"Chat-Fehler: {e}")
        return "Entschuldigung Arsenij, ich habe gerade technische Probleme."


def tts_generate(text: str, lang: str = "de") -> bytes | None:
    """ElevenLabs TTS — natuerliche Stimme ohne starken Akzent."""
    try:
        if not ELEVENLABS_KEY:
            logger.warning("ElevenLabs API Key fehlt - kein Audio moeglich.")
            return None
        import re
        clean = re.sub(r'\*+|`+|#+', '', text).strip()
        # Namen phonetisch korrekt fuer ElevenLabs
        clean = re.sub(r'\bArsenij\b', 'Arseniy', clean)
        clean = re.sub(r'\barsenij\b', 'arseniy', clean)
        clean = clean[:900]
        if not clean:
            return None

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}"
        payload = json.dumps({
            "text": clean,
            "model_id": "eleven_multilingual_v2",
            "language_code": "de" if lang == "de" else "en",
            "voice_settings": {
                # Hohe stability = sehr konsistente Aussprache, kein Akzentdrift
                "stability": 0.52,
                # Hoher similarity_boost = klar und deutlich wie die Originalstimme
                "similarity_boost": 0.78,
                # Niedriger style = natuerlich und unaufgeregt, kein Theaterton
                "style": 0.12,
                "use_speaker_boost": True,
            },
        }).encode()

        req = urllib.request.Request(url, data=payload, headers={
            "xi-api-key": ELEVENLABS_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }, method="POST")

        with urllib.request.urlopen(req, timeout=20) as resp:
            audio = resp.read()

        logger.info(f"TTS: {len(audio)} bytes ({lang})")
        return audio

    except Exception as e:
        logger.error(f"TTS Fehler: {e}")
        return None


def detect_lang(text: str) -> str:
    """Sprache erkennen (de oder en)."""
    de_chars = sum(1 for c in text if c in "äöüÄÖÜß")
    de_words = ["ich", "du", "ist", "der", "die", "das", "und", "nicht", "wie", "was", "eine", "einen"]
    de_count = sum(1 for w in de_words if f" {w} " in f" {text.lower()} ")
    return "de" if (de_chars > 0 or de_count >= 2) else "en"


class JarvisHandler(SimpleHTTPRequestHandler):
    """HTTP Handler fuer Jarvis Web-Interface."""

    sessions: dict = {}
    pending_reads: dict = {}   # session_id → verbleibender Text fuer "weiterlesen"

    def log_message(self, format, *args):
        if "/chat" in str(args) or "/search" in str(args):
            logger.info(f"API: {args[0]}")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_GET(self):
        if self.path == "/api/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "model": MODEL,
                "ollama_url": OLLAMA_URL,
                "voice": ELEVENLABS_VOICE,
            }).encode())
            return

        if self.path == "/" or self.path == "/index.html":
            self.path = "/jarvis_voice.html"

        # Alle anderen statischen Dateien
        base = Path(__file__).parent
        file_path = base / self.path.lstrip("/")

        if file_path.exists() and file_path.is_file():
            self.send_response(200)
            if self.path.endswith(".html"):
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
            elif self.path.endswith(".js"):
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Cache-Control", "no-store")
            elif self.path.endswith(".css"):
                self.send_header("Content-Type", "text/css")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if self.path == "/api/chat":
            try:
                data = json.loads(body)
                message = data.get("message", "")
                session_id = data.get("session_id", "default")
                use_search = data.get("use_search", True)

                if session_id not in JarvisHandler.sessions:
                    JarvisHandler.sessions[session_id] = []

                history = JarvisHandler.sessions[session_id]
                response = chat_with_jarvis(message, history, use_search)

                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": response})
                # Max 20 Nachrichten im Verlauf behalten
                if len(history) > 20:
                    JarvisHandler.sessions[session_id] = history[-20:]

                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self._cors_headers()
                    self.end_headers()
                    lang = detect_lang(response)
                    self.wfile.write(json.dumps({
                        "response": response,
                        "searched": use_search and needs_search(message),
                        "lang": lang
                    }).encode())
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    logger.info("Client hat /api/chat vor dem Abschluss geschlossen.")

            except Exception as e:
                if isinstance(e, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
                    logger.info("Client hat /api/chat waehrend der Antwort getrennt.")
                    return
                try:
                    self.send_response(500)
                    self._cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    logger.info("Client war bereits getrennt, 500 fuer /api/chat nicht mehr zustellbar.")

        elif self.path == "/api/stream":
            # SSE Streaming: Text live + Satz-Audio
            try:
                import re as _re
                data = json.loads(body)
                message    = data.get("message", "")
                session_id = data.get("session_id", "default")
                use_search = data.get("use_search", True)

                if session_id not in JarvisHandler.sessions:
                    JarvisHandler.sessions[session_id] = []
                history = JarvisHandler.sessions[session_id]

                # SSE Headers
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self._cors_headers()
                self.end_headers()

                def sse(event: str, payload: dict):
                    line = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    try:
                        self.wfile.write(line.encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as disconnect:
                        raise ConnectionAbortedError("client_disconnected") from disconnect

                # ── WEITERLESEN: User antwortete "ja" auf "Soll ich weiterlesen?" ──
                if session_id in JarvisHandler.pending_reads and is_weiterlesen_reply(message):
                    pending_text = JarvisHandler.pending_reads.pop(session_id)
                    lang = detect_lang(pending_text)

                    # Text in Saetze aufteilen
                    raw_sents = _re.split(r'(?<=[.!?\n])\s*', pending_text)
                    sentences_all = [s.strip() for s in raw_sents if len(s.strip()) > 6]

                    # Naechsten Chunk bis READ_LIMIT sammeln
                    to_speak, remaining, chars = [], [], 0
                    for s in sentences_all:
                        if chars < READ_LIMIT:
                            to_speak.append(s); chars += len(s)
                        else:
                            remaining.append(s)

                    speak_text = " ".join(to_speak)
                    sse("text", {"chunk": speak_text, "searched": False})

                    # TTS fuer Saetze dieses Chunks
                    futures = {i: (s, tts_executor.submit(tts_generate, s, lang)) for i, s in enumerate(to_speak)}
                    for i in range(len(to_speak)):
                        s, fut = futures[i]
                        try:
                            ab = fut.result(timeout=30)
                        except Exception:
                            ab = None
                        if ab:
                            sse("audio", {"idx": i, "sentence": s, "data": base64.b64encode(ab).decode()})
                        else:
                            sse("audio_skip", {"idx": i})

                    next_idx = len(to_speak)
                    full_out = speak_text

                    if remaining:
                        JarvisHandler.pending_reads[session_id] = " ".join(remaining)
                        wq = "Soll ich weiterlesen, Arsenij?"
                        try:
                            wab = tts_executor.submit(tts_generate, wq, "de").result(timeout=20)
                        except Exception:
                            wab = None
                        if wab:
                            sse("audio", {"idx": next_idx, "sentence": wq, "data": base64.b64encode(wab).decode()})
                        else:
                            sse("audio_skip", {"idx": next_idx})
                        full_out += " " + wq

                    JarvisHandler.sessions[session_id].append({"role": "user", "content": message})
                    JarvisHandler.sessions[session_id].append({"role": "assistant", "content": full_out})
                    sse("done", {"full": full_out, "lang": lang, "searched": False})
                    return

                # ── User fragt etwas Neues: pending read verwerfen ──
                if session_id in JarvisHandler.pending_reads:
                    del JarvisHandler.pending_reads[session_id]

                # ── Brave Search vorab (falls noetig) ──
                search_ctx = ""
                if use_search and needs_search(message):
                    sse("status", {"text": "Suche im Web..."})
                    search_ctx = "\n\nAktuelle Web-Ergebnisse:\n" + brave_search(message)

                # ── Aktuelle Uhrzeit & Datum immer im Kontext ──
                import datetime as _dt
                now = _dt.datetime.now()
                time_ctx = (f"Aktuelle Zeit: {now.strftime('%H:%M')} Uhr, "
                            f"{now.strftime('%A')} der {now.strftime('%d.%m.%Y')}.")
                system_with_time = SYSTEM_PROMPT + "\n\n" + time_ctx

                # Nachrichten zusammenbauen
                messages_list = [{"role": "system", "content": system_with_time}]
                for entry in history[-12:]:
                    messages_list.append(entry)
                user_content = message + search_ctx if search_ctx else message
                messages_list.append({"role": "user", "content": user_content})

                # Streaming von Ollama
                full_response = ""
                sentence_buf  = ""
                sentence_idx  = 0
                next_audio_idx = 0
                audio_futures = {}
                SENTENCE_ENDS = {".", "!", "?", "\n"}
                tts_chars_queued = 0      # Chars die bereits als TTS eingeplant sind
                read_limit_hit   = False  # Wurde READ_LIMIT ueberschritten?
                pending_sentences = []    # Saetze nach dem Limit

                def flush_ready_audio(block: bool = False):
                    nonlocal next_audio_idx
                    while next_audio_idx in audio_futures:
                        sentence, future = audio_futures[next_audio_idx]
                        if not block and not future.done():
                            break
                        try:
                            audio_bytes = future.result(timeout=20 if block else 0)
                        except Exception as audio_err:
                            logger.error(f"TTS Future Fehler: {audio_err}")
                            audio_bytes = None
                        if audio_bytes:
                            b64 = base64.b64encode(audio_bytes).decode()
                            sse("audio", {"idx": next_audio_idx, "sentence": sentence, "data": b64})
                        else:
                            sse("audio_skip", {"idx": next_audio_idx})
                        del audio_futures[next_audio_idx]
                        next_audio_idx += 1

                for token in stream_ollama_tokens(messages_list):
                    full_response += token
                    sentence_buf  += token
                    sse("text", {"chunk": token})

                    for end_ch in SENTENCE_ENDS:
                        while end_ch in sentence_buf:
                            idx_ch = sentence_buf.index(end_ch)
                            sentence = sentence_buf[:idx_ch + 1].strip()
                            sentence_buf = sentence_buf[idx_ch + 1:]
                            if len(sentence) > 6:
                                if not read_limit_hit and tts_chars_queued < READ_LIMIT:
                                    audio_futures[sentence_idx] = (
                                        sentence,
                                        tts_executor.submit(tts_generate, sentence),
                                    )
                                    sentence_idx += 1
                                    tts_chars_queued += len(sentence)
                                    if tts_chars_queued >= READ_LIMIT:
                                        read_limit_hit = True
                                else:
                                    read_limit_hit = True
                                    pending_sentences.append(sentence)
                    flush_ready_audio()

                # Letzten Rest
                leftover = sentence_buf.strip()
                if len(leftover) > 6:
                    if not read_limit_hit and tts_chars_queued < READ_LIMIT:
                        audio_futures[sentence_idx] = (
                            leftover,
                            tts_executor.submit(tts_generate, leftover),
                        )
                        sentence_idx += 1
                    else:
                        pending_sentences.append(leftover)

                while audio_futures:
                    flush_ready_audio(block=True)

                # Falls es mehr zu lesen gibt: "Soll ich weiterlesen?" fragen
                if pending_sentences:
                    pending_text = " ".join(pending_sentences)
                    JarvisHandler.pending_reads[session_id] = pending_text
                    wq = "Soll ich weiterlesen, Arsenij?"
                    try:
                        wab = tts_executor.submit(tts_generate, wq, "de").result(timeout=20)
                    except Exception:
                        wab = None
                    if wab:
                        sse("audio", {"idx": sentence_idx, "sentence": wq,
                                      "data": base64.b64encode(wab).decode()})
                    else:
                        sse("audio_skip", {"idx": sentence_idx})
                    full_response += " " + wq

                # Verlauf speichern
                JarvisHandler.sessions[session_id].append({"role": "user", "content": message})
                JarvisHandler.sessions[session_id].append({"role": "assistant", "content": full_response})
                if len(JarvisHandler.sessions[session_id]) > 20:
                    JarvisHandler.sessions[session_id] = JarvisHandler.sessions[session_id][-20:]

                lang = detect_lang(full_response)
                sse("done", {"full": full_response, "lang": lang, "searched": bool(search_ctx)})

            except Exception as e:
                if isinstance(e, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)) or "client_disconnected" in str(e):
                    logger.info("Client hat /api/stream vorzeitig geschlossen.")
                    return
                logger.error(f"Stream-Fehler: {e}")
                try:
                    self.wfile.write(f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n".encode())
                    self.wfile.flush()
                except Exception:
                    pass

        elif self.path == "/api/clear":
            try:
                data = json.loads(body)
                session_id = data.get("session_id", "default")
                JarvisHandler.sessions[session_id] = []
                self.send_response(200)
                self._cors_headers()
                self.end_headers()
                self.wfile.write(b'{"ok": true}')
            except Exception:
                self.send_response(500)
                self.end_headers()

        elif self.path == "/api/tts":
            try:
                data = json.loads(body)
                text = data.get("text", "")
                lang = data.get("lang", "de")
                audio = tts_generate(text, lang)
                if audio:
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Content-Length", str(len(audio)))
                    self._cors_headers()
                    self.end_headers()
                    self.wfile.write(audio)
                else:
                    self.send_response(503)
                    self._cors_headers()
                    self.end_headers()
                    self.wfile.write(b'{"error":"tts_unavailable"}')
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except Exception as e:
                logger.error(f"TTS-Endpoint Fehler: {e}")
                try:
                    self.send_response(500)
                    self._cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
                except Exception:
                    pass

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")


def main():
    logger.info("=" * 50)
    logger.info("  Clark Server startet...")
    logger.info(f"  URL: http://localhost:{PORT}")
    logger.info(f"  Ollama: {OLLAMA_URL}")
    logger.info(f"  Brave Search: aktiviert")
    logger.info(f"  ElevenLabs Voice: {ELEVENLABS_VOICE}")
    logger.info("=" * 50)

    import os
    os.chdir(Path(__file__).parent)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), JarvisHandler)

    import webbrowser
    threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

    logger.info("Browser oeffnet sich automatisch...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server gestoppt.")


if __name__ == "__main__":
    main()
