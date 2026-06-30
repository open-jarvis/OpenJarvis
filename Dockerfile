# Multi-stage production Dockerfile for OpenJarvis

# Stage 1: Build dependencies
FROM python:3.12-slim as builder

WORKDIR /build

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Build Python dependencies wheel
RUN uv pip install --python 3.12 -r <(uv export --no-dev) --wheel --wheel-dir=/wheels

# Stage 2: Rust build (if needed)
FROM rust:latest as rust-builder

WORKDIR /build

COPY rust/ ./rust/

RUN cd rust/crates/openjarvis-python && \
    cargo build --release

# Stage 3: Runtime
FROM python:3.12-slim

LABEL maintainer="OpenJarvis Contributors"
LABEL description="Personal AI, On Personal Devices - Production Deployment"

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder
COPY --from=builder /wheels /wheels

# Install Python packages
RUN pip install --no-index --find-links=/wheels -r /wheels/requirements.txt && \
    rm -rf /wheels

# Copy application code
COPY src/ /app/src/
COPY scripts/ /app/scripts/

# Copy Rust extension if built
COPY --from=rust-builder /build/target/release/*.so /app/

# Create non-root user for security
RUN useradd -m -u 1000 openjarvis && chown -R openjarvis:openjarvis /app

USER openjarvis

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose ports
EXPOSE 8000 8001

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/app/scripts:$PATH"

# Default command
CMD ["python", "-m", "openjarvis.server"]
