# Cloud Provider API Keys

OpenJarvis supports 10+ cloud LLM providers alongside local inference engines. Each provider requires an API key set as an environment variable. The application reads these directly from the process environment — no configuration file changes are needed when deploying on Railway or with Docker.

## Supported Providers

### OpenAI

| Environment Variable | Description |
|----------------------|-------------|
| `OPENAI_API_KEY` | API key from [platform.openai.com](https://platform.openai.com/api-keys) |

**Available models:** `gpt-4o`, `gpt-4o-mini`, `gpt-5-mini`, `gpt-5-mini-2025-08-07`, `o1-*`, `o3-*`, `o4-*`

---

### Anthropic

| Environment Variable | Description |
|----------------------|-------------|
| `ANTHROPIC_API_KEY` | API key from [console.anthropic.com](https://console.anthropic.com/settings/keys) |

**Available models:** `claude-sonnet-4-20250514`, `claude-opus-4-20250514`, `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`

---

### Google Gemini

| Environment Variable | Description |
|----------------------|-------------|
| `GEMINI_API_KEY` | Primary API key from [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| `GEMINI_API_KEY_B` | Secondary Gemini key (optional, for quota balancing) |

**Available models:** `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-3-pro`, `gemini-3-flash`

---

### Groq

| Environment Variable | Description |
|----------------------|-------------|
| `GROQ_API_KEY` | API key from [console.groq.com](https://console.groq.com/keys) |
| `GROQ_ENABLED` | Set to `true` to enable Groq routing (optional flag) |

**Available models:** `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `mixtral-8x7b-32768`, `gemma2-9b-it`

---

### DeepSeek

| Environment Variable | Description |
|----------------------|-------------|
| `DEEPSEEK_API_KEY` | API key from [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| `DEEPSEEK_ENABLED` | Set to `true` to enable DeepSeek routing (optional flag) |

**Available models:** `deepseek-chat` (DeepSeek-V3), `deepseek-reasoner` (DeepSeek-R1)

---

### OpenRouter

| Environment Variable | Description |
|----------------------|-------------|
| `OPENROUTER_API_KEY` | API key from [openrouter.ai/keys](https://openrouter.ai/keys) |
| `OPENROUTER_ENABLED` | Set to `true` to enable OpenRouter routing (optional flag) |

**Available models:** 200+ models from all major providers via the `provider/model-name` format (e.g. `meta-llama/llama-3-8b-instruct`)

---

### Cerebras

| Environment Variable | Description |
|----------------------|-------------|
| `CEREBRAS_API_KEY` | API key from [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| `CEREBRAS_ENABLED` | Set to `true` to enable Cerebras routing (optional flag) |

**Available models:** Use the `cerebras/` prefix, e.g. `cerebras/llama3.1-70b`

---

### SambaNova

| Environment Variable | Description |
|----------------------|-------------|
| `SAMBANOVA_API_KEY` | API key from [cloud.sambanova.ai](https://cloud.sambanova.ai) |
| `SAMBANOVA_ENABLED` | Set to `true` to enable SambaNova routing (optional flag) |

**Available models:** Use the `sambanova/` prefix, e.g. `sambanova/Meta-Llama-3.3-70B-Instruct`

---

### Kimi (Moonshot AI)

| Environment Variable | Description |
|----------------------|-------------|
| `KIMI_API_KEY` | API key from [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys) |
| `KIMI_ENABLED` | Set to `true` to enable Kimi routing (optional flag) |

**Available models:** `moonshot-v1-8k`, `moonshot-v1-32k`, `moonshot-v1-128k`, `kimi-k2`

---

### V0

| Environment Variable | Description |
|----------------------|-------------|
| `V0_API_KEY` | API key for V0 models |

**Available models:** `v0-*` prefixed models

---

### MiniMax

| Environment Variable | Description |
|----------------------|-------------|
| `MINIMAX_API_KEY` | API key from [platform.minimaxi.com](https://platform.minimaxi.com) |

**Available models:** `MiniMax-M2.7`, `MiniMax-M2.7-highspeed`, `MiniMax-M2.5`, `MiniMax-M2.5-highspeed`

---

## Setting Environment Variables

### Railway

Set each variable in your Railway service's **Variables** tab. Railway injects them into the container at runtime — no Dockerfile changes are needed beyond what is already declared.

### Docker CLI

Pass keys at `docker run` time:

```bash
docker run -d -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e GEMINI_API_KEY=AIza... \
  -e GROQ_API_KEY=gsk_... \
  openjarvis:latest
```

### Docker Compose

Add an `environment` block to the `jarvis` service:

```yaml
services:
  jarvis:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - GROQ_API_KEY=${GROQ_API_KEY}
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - CEREBRAS_API_KEY=${CEREBRAS_API_KEY}
      - SAMBANOVA_API_KEY=${SAMBANOVA_API_KEY}
      - KIMI_API_KEY=${KIMI_API_KEY}
      - V0_API_KEY=${V0_API_KEY}
```

Store the actual values in a `.env` file (never commit it to version control):

```bash
# .env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
GROQ_API_KEY=gsk_...
DEEPSEEK_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...
CEREBRAS_API_KEY=csk-...
SAMBANOVA_API_KEY=...
KIMI_API_KEY=sk-...
V0_API_KEY=...
```

### cloud-keys.env file

Alternatively, create `~/.openjarvis/cloud-keys.env` on the host (or mount it into the container). The cloud router reads this file at request time, so keys can be updated without restarting the server:

```bash
# ~/.openjarvis/cloud-keys.env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
GROQ_API_KEY=gsk_...
DEEPSEEK_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...
CEREBRAS_API_KEY=csk-...
SAMBANOVA_API_KEY=...
KIMI_API_KEY=sk-...
V0_API_KEY=...
```

## Model Routing

The cloud router (`src/openjarvis/server/cloud_router.py`) automatically detects the provider from the model name prefix:

| Model prefix | Provider | API key used |
|---|---|---|
| `gpt-`, `o1-`, `o3-`, `o4-`, `chatgpt-` | OpenAI | `OPENAI_API_KEY` |
| `claude-` | Anthropic | `ANTHROPIC_API_KEY` |
| `gemini-` | Google | `GEMINI_API_KEY` |
| `deepseek-` | DeepSeek | `DEEPSEEK_API_KEY` |
| `llama-3`, `llama3-`, `mixtral-`, `gemma2-` | Groq | `GROQ_API_KEY` |
| `cerebras/` | Cerebras | `CEREBRAS_API_KEY` |
| `sambanova/` | SambaNova | `SAMBANOVA_API_KEY` |
| `moonshot-`, `kimi-` | Kimi | `KIMI_API_KEY` |
| `v0-` | V0 | `V0_API_KEY` |
| `MiniMax-` | MiniMax | `MINIMAX_API_KEY` |
| `provider/model` (slash, not in above) | OpenRouter | `OPENROUTER_API_KEY` |

Local model IDs (Ollama, vLLM, llama.cpp, etc.) are never routed to cloud providers.
