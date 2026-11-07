# Document QA

Index a directory of documents into FridayAI memory and answer questions
with context-augmented retrieval and citations.

## Requirements

- FridayAI installed (`git clone https://github.com/open-jarvis/FridayAI.git && cd FridayAI && uv sync` or `uv sync --extra dev`)
- An inference engine running (Ollama, cloud API, vLLM, etc.)
- A memory backend available (SQLite is the built-in default)

## Usage

```bash
python examples/doc_qa/doc_qa.py --help
python examples/doc_qa/doc_qa.py --docs-path ./docs --query "How does authentication work?"
python examples/doc_qa/doc_qa.py --docs-path ./papers --query "What are the main findings?" \
    --model gpt-4o --engine cloud --chunk-size 256 --top-k 10
```

## How It Works

The script performs two steps:

1. **Index** -- Uses `Friday.memory.index()` to chunk the documents at
   `--docs-path` and store them in the memory backend. Each chunk is stored
   with its source path so answers can cite specific files.

2. **Ask** -- Uses `j.ask(query, context=True)` which automatically retrieves
   the most relevant chunks from memory and injects them as context before
   sending the query to the model. The model produces an answer grounded in the
   retrieved documents.

This is the retrieval-augmented generation (RAG) pattern built into the
FridayAI SDK. Adjust `--chunk-size` and `--top-k` to tune the
retrieval quality for your documents.
