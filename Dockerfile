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

# Stage 3: Runtime
FROM python:3.12-slim-bookworm

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

# Placeholder for future auth re-enablement; override at runtime if needed.
# All provider API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.) are read
# directly from Railway's runtime environment — no defaults are set here so
# they are never stomped by empty Dockerfile values.
ENV OPENJARVIS_API_KEY=default-key-change-me

EXPOSE 8000

CMD exec jarvis serve --host 0.0.0.0 --port ${PORT:-8000}
