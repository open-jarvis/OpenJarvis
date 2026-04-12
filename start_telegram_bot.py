"""
Jarvis Telegram Bot - Arsenij's Personal Assistant
Starten mit: uv run python start_telegram_bot.py
"""

import logging
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

from jarvis_secrets import load_secret
from jarvis_transcription import transcribe_audio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = load_secret(
    "telegram_bot_token",
    env_names=("TELEGRAM_BOT_TOKEN", "BOT_TOKEN"),
    config_path=("channel", "telegram", "token"),
)
JARVIS_SERVER = os.getenv("CLARK_SERVER_URL", "http://localhost:7777")

SYSTEM_PROMPT = """Du bist Clark, der persoenliche KI-Assistent von Arsenij.
Du agierst wie eine Kombination aus einem diskreten Butler, Siri, Gemini und einem smarten Mitarbeiter — hilfsbereit, proaktiv, direkt.

WICHTIG:
- Du heisst Clark. Du bist Clark.
- Der Nutzer heisst Arsenij.
- Nenne Arsenij beim Namen wenn es natuerlich ist.
- Antworte immer in der Sprache in der Arsenij schreibt (Deutsch oder Englisch).
- Sei direkt, hoeflich und deutlich butlerhaft — kein unnoetiges Gerede.
- Antworte kontrolliert, kultiviert und ruhig, nie hektisch oder slanglastig.
- Wenn es passt, wirke vorausschauend wie ein diskreter Hausbutler.
- Merke dir den Gespraechsverlauf innerhalb der Session.
- Wenn du etwas nicht weisst, sag es ehrlich.
- Nutze dein Wissen aktiv um hilfreiche Antworten zu geben.

Du bist Arsenijs lokaler, privater Assistent — keine Daten verlassen seinen PC."""

# Chat-Verlauf pro User
chat_histories: dict = {}
executor = ThreadPoolExecutor(max_workers=2)


def get_jarvis_response(user_message: str, history: list) -> str:
    """Jarvis-Antwort ueber Server (mit Brave Search) oder Ollama direkt."""
    try:
        import httpx
        # Jarvis-Server nutzen — hat Brave Search eingebaut
        resp = httpx.post(
            f"{JARVIS_SERVER}/api/chat",
            json={"message": user_message, "session_id": f"tg_{abs(hash(str(history[:2])))}", "use_search": True},
            timeout=120.0,
        )
        data = resp.json()
        return data.get("response", "Keine Antwort.")
    except Exception:
        # Fallback: direkt Ollama ohne Search
        try:
            import httpx
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for entry in history[-10:]:
                messages.append(entry)
            messages.append({"role": "user", "content": user_message})
            resp = httpx.post(
                "http://localhost:11434/api/chat",
                json={"model": "qwen3:8b", "messages": messages, "stream": False},
                timeout=120.0,
            )
            return resp.json()["message"]["content"]
        except Exception as e:
            logger.error(f"Fehler: {e}")
            return "Entschuldigung Arsenij, ich habe gerade technische Probleme."


def transcribe_voice(file_path: str) -> str:
    """Sprachnachricht ueber die gemeinsame Whisper-Pipeline transkribieren."""
    result = transcribe_audio(file_path, preferred_language="de")
    return result.get("text", "")


def main():
    if not BOT_TOKEN:
        logger.error("Telegram Bot Token fehlt. Lege ihn lokal in ~/.openjarvis/config.toml, ~/.openjarvis/clark_secrets.toml oder per TELEGRAM_BOT_TOKEN ab.")
        sys.exit(1)

    try:
        from telegram import Update
        from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
    except ImportError:
        logger.error("python-telegram-bot nicht installiert!")
        logger.error("Bitte ausfuehren: uv sync --extra channel-telegram")
        sys.exit(1)

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Hallo Arsenij! Ich bin Clark, dein persoenlicher Assistent.\n"
            "Ich laufe lokal auf deinem PC - keine Daten verlassen dein System!\n\n"
            "Befehle:\n"
            "/clear - Gespraechsverlauf loeschen\n"
            "/help  - Alle Befehle anzeigen\n\n"
            "Du kannst mir Text- UND Sprachnachrichten schicken!"
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Clark Befehle:\n\n"
            "/clear  - Gespraechsverlauf loeschen\n"
            "/help   - Diese Hilfe\n\n"
            "Sprachnachrichten werden automatisch transkribiert.\n"
            "Einfach eine Sprachnachricht schicken!"
        )

    async def process_and_reply(update: Update, context, user_message: str):
        """Nachricht verarbeiten und antworten."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        logger.info(f"Nachricht: {user_message[:60]}...")
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        if user_id not in chat_histories:
            chat_histories[user_id] = []

        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            executor,
            get_jarvis_response,
            user_message,
            list(chat_histories[user_id]),
        )

        chat_histories[user_id].append({"role": "user", "content": user_message})
        chat_histories[user_id].append({"role": "assistant", "content": response})

        max_len = 4096
        for i in range(0, len(response), max_len):
            await update.message.reply_text(response[i:i + max_len])

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        await process_and_reply(update, context, update.message.text)

    async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Sprachnachrichten empfangen und transkribieren."""
        if not update.message or not update.message.voice:
            return

        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        try:
            voice_file = await context.bot.get_file(update.message.voice.file_id)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                tmp_path = tmp.name
            await voice_file.download_to_drive(tmp_path)

            import asyncio
            loop = asyncio.get_event_loop()
            transcript = await loop.run_in_executor(executor, transcribe_voice, tmp_path)
            os.unlink(tmp_path)

            if transcript:
                await update.message.reply_text(f"Ich hoere: _{transcript}_", parse_mode="Markdown")
                await process_and_reply(update, context, transcript)
            else:
                await update.message.reply_text(
                    "Spracherkennung nicht verfuegbar. Installiere faster-whisper:\n"
                    "uv sync --extra speech"
                )
        except Exception as e:
            logger.error(f"Voice-Fehler: {e}")
            await update.message.reply_text("Sprachnachricht konnte nicht verarbeitet werden.")

    async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        chat_histories[user_id] = []
        await update.message.reply_text("Gespraechsverlauf geloescht, Arsenij!")

    # Bot aufbauen und direkt starten (KEIN asyncio.run!)
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("=" * 50)
    logger.info("  Clark Telegram-Bot gestartet!")
    logger.info("  Schreib deinem Bot auf Telegram")
    logger.info("  Strg+C zum Beenden")
    logger.info("=" * 50)

    # run_polling verwaltet den Event-Loop selbst
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
