import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(BASE_DIR, "storage.json")


class MemoryManager:
    def __init__(self):
        if not os.path.exists(FILE):
            with open(FILE, "w") as f:
                json.dump({"memories": []}, f)

    def _load(self):
        with open(FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data):
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def add(self, text, role="user"):
        data = self._load()

        data["memories"].append({
            "text": text,
            "role": role,
            "time": str(datetime.now())
        })

        self._save(data)

    def search(self, query):
        data = self._load()
        results = []

        for m in data["memories"]:
            if query.lower() in m["text"].lower():
                results.append(m["text"])

        return results[-5:]

    def build_context(self, query):
        results = self.search(query)

        if not results:
            return ""

        return "MEMORY:\n" + "\n".join(results)
