# Stage 1: Build frontend SPA
FROM node:22-slim AS frontend

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install
COPY frontend/ .
RUN npm run build

# Stage 2: Build Python package
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY scripts/install scripts/install
COPY deploy/windows deploy/windows

# Copy built frontend into the server static directory
COPY --from=frontend /src/openjarvis/server/static src/openjarvis/server/static/

# `,speech` pulls faster-whisper for multilingual server-side STT.
RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server,speech]"

# Stage 3: Runtime
FROM python:3.12-slim-bookworm

# ffmpeg: decode browser webm/opus audio for faster-whisper.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

# Bake the cloud config (OpenRouter model + Whisper + reply-in-user-language).
COPY deploy/fly/config.toml /root/.openjarvis/config.toml

EXPOSE 8000

ENTRYPOINT ["jarvis"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
