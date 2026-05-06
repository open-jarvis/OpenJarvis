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

# Copy built frontend into the server static directory
COPY --from=frontend /app/src/openjarvis/server/static src/openjarvis/server/static/

RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server]"

# Stage 3: Runtime
FROM python:3.12-slim-bookworm

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["jarvis"]
CMD ["sh", "-c", "jarvis serve --host 0.0.0.0 --port ${PORT:-8000}"]
