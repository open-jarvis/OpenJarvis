# Stage 1: Build frontend SPA
FROM node:22-slim AS frontend

WORKDIR /app
COPY frontend/ ./frontend/
RUN cd frontend && npm ci --ignore-scripts 2>/dev/null || npm install
RUN cd frontend && npm run build

# Stage 2: Build Python package
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY rust/ rust/

# Copy built frontend into the server static directory
COPY --from=frontend /app/src/openjarvis/server/static src/openjarvis/server/static/

RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server]"

# Install curl and build dependencies for Rust
RUN apt-get update && apt-get install -y curl build-essential && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain and build extension in single RUN
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && \
    . $HOME/.cargo/env && \
    uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml && \
    echo "Looking for wheel..." && \
    find /tmp -name "openjarvis_rust-*.whl" -type f && \
    find /tmp -name "openjarvis_rust-*.whl" -type f -exec pip install -v --no-cache-dir {} \; && \
    python -c "import openjarvis_rust; print('✓ Rust extension imported successfully')"

# Stage 3: Runtime
FROM python:3.12-slim-bookworm

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

# Set default API key if not provided at runtime
ENV OPENJARVIS_API_KEY=default-key-change-me

# Cloud provider API keys — set these at runtime via Railway / Docker env vars.
# The application reads them directly from the environment; no value is baked
# into the image.  Declaring them here makes them visible to tooling and
# ensures they are forwarded into the container process.
ENV OPENAI_API_KEY=""
ENV ANTHROPIC_API_KEY=""
ENV GEMINI_API_KEY=""
ENV GEMINI_API_KEY_B=""
ENV GROQ_API_KEY=""
ENV DEEPSEEK_API_KEY=""
ENV OPENROUTER_API_KEY=""
ENV CEREBRAS_API_KEY=""
ENV SAMBANOVA_API_KEY=""
ENV KIMI_API_KEY=""
ENV V0_API_KEY=""
ENV MINIMAX_API_KEY=""

# Provider feature flags (set to "true" to enable)
ENV GROQ_ENABLED=""
ENV DEEPSEEK_ENABLED=""
ENV OPENROUTER_ENABLED=""
ENV CEREBRAS_ENABLED=""
ENV SAMBANOVA_ENABLED=""
ENV KIMI_ENABLED=""
ENV HF_ENABLED=""
ENV GLM_ENABLED=""

EXPOSE 8000

CMD exec jarvis serve --host 0.0.0.0 --port ${PORT:-8000}
