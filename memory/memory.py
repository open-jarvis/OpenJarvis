import json
import os
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, "storage.json")


def init_storage():
    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"memories": []}, f, indent=4)


def load_memory():
    init_storage()
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def is_important(text: str) -> bool:
    keywords = [
        "progetto",
        "sto creando",
        "sto lavorando",
        "ricorda",
        "importante",
        "build",
        "app",
        "flask",
        "jarvis",
        "codice",
        "sviluppo"
    ]

    text_lower = text.lower()
    return any(k in text_lower for k in keywords)


def add_memory(text: str, category: str = "general"):
    data = load_memory()

    memory_item = {
        "text": text,
        "category": category,
        "timestamp": datetime.now().isoformat()
    }

    data["memories"].append(memory_item)
    save_memory(data)

def search_memory(query: str):
    data = load_memory()
    results = []

    query_lower = query.lower()

    for mem in data["memories"]:
        if query_lower in mem["text"].lower():
            results.append(mem)

    return results


def build_context(query: str, limit: int = 5) -> str:
    results = search_memory(query)

    if not results:
        return ""

    context_lines = []
    for r in results[:limit]:
        context_lines.append(f"- {r['text']}")

    return "\n".join(context_lines)


def process_user_message(message: str):
    """
    Usa questa funzione ogni volta che l'utente scrive qualcosa.
    """

    if is_important(message):
        add_memory(message, category="important")


def get_llm_context(user_message: str) -> str:
    context = build_context(user_message)

    if context:
        return f"""MEMORIA UTENTE:
{context}

---"""

    return ""
    return ""