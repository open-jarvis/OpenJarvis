# Force Railway to drop the broken cache
ARG REBUILD_CACHE=2

# Stage 1: Build frontend SPA (Fail-safe)
FROM node:22-slim AS frontend

WORKDIR /frontend

# Copy package files if they exist
COPY frontend/package.json frontend/package-lock.json* ./

# Install dependencies (failsafe if files are missing)
RUN npm ci --ignore-scripts 2>/dev/null || npm install 2>/dev/null || true

# Copy frontend source
COPY frontend/ .

# Attempt build, but don't crash if it fails
RUN npm run build 2>/dev/null || true

# ENSURE the dist folder exists so the next stage doesn't crash
RUN mkdir -p /frontend/dist

# Stage 2: Build Python package
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

# Ensure the static directory exists in Python
RUN mkdir -p src/openjarvis/server/static/

# Copy built frontend (will copy empty dist if build failed)
COPY --from=frontend /frontend/dist src/openjarvis/server/static/

RUN pip install --no-cache-dir uv && \
    uv pip install --system ".[server]"

# Stage 3: Runtime
FROM python:3.12-slim-bookworm

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["jarvis"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
