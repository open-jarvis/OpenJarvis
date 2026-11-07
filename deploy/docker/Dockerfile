# Base images are pinned to an immutable digest (in addition to a human-readable
# tag) so every build resolves the exact same layers — reproducible builds and
# safe rollbacks (#563).

# Stage 1: Build frontend SPA
FROM node:22.23.0-slim@sha256:d9f850096136edbc402debdd8729579a288aac64574ada0ff4db26b6ae58b0b2 AS frontend
# Public Supabase anon key for the savings leaderboard; empty by default so
# the image's leaderboard stays disabled (#589). Pass --build-arg to enable.
ARG FRIDAY_AI_LEADERBOARD_PUBLIC_ANON=

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install
COPY frontend/ .
RUN VITE_SUPABASE_ANON_KEY="${FRIDAY_AI_LEADERBOARD_PUBLIC_ANON}" npm run build

# Stage 2: Build Python package
FROM python:3.12.13-slim-bookworm@sha256:76d4b7b6305788c6b4c6a19d6a22a3921bf802e9af4d5e1e5bd771208dba74bf AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${PATH}"

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
        sh -s -- -y --profile minimal --default-toolchain none && \
    rustup toolchain install 1.88 --profile minimal && \
    rustup default 1.88

WORKDIR /app

# Install dependencies from the committed lockfile (#567). `uv export --frozen`
# reads uv.lock as-is (no re-resolution) and emits a fully pinned, hash-verified
# requirements set; `--no-deps` then installs exactly that set. This is a
# separate layer from the source copy so dependency installs stay cached when
# only application code changes.
COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv && \
    uv export --frozen --no-dev --extra server --no-emit-project > requirements.txt && \
    uv pip install --system --no-deps -r requirements.txt && \
    uv pip install --system --no-deps "maturin>=1.12.6,<2"

# Copy the source and the non-src force-include paths (see pyproject
# [tool.hatch.build.targets.wheel.force-include]) before building the project.
COPY src/ src/
COPY rust/ rust/
COPY scripts/install scripts/install
COPY deploy/windows deploy/windows

# Copy built frontend into the server static directory
COPY --from=frontend /src/friday_ai/server/static src/friday_ai/server/static/

# Install the project itself without re-resolving dependencies.
RUN uv pip install --system --no-deps . && \
    maturin build --release \
        --manifest-path rust/crates/friday_ai-python/Cargo.toml \
        --interpreter python3 \
        --out /tmp/friday_ai-rust-wheel && \
    uv pip install --system --no-deps /tmp/friday_ai-rust-wheel/*.whl && \
    python3 -c "import friday_ai_rust; print('friday_ai_rust ok')" && \
    python3 -m pip uninstall -y maturin && \
    rm -rf /tmp/friday_ai-rust-wheel rust

# Stage 3: Runtime
FROM python:3.12.13-slim-bookworm@sha256:76d4b7b6305788c6b4c6a19d6a22a3921bf802e9af4d5e1e5bd771208dba74bf

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

# Run as an unprivileged user — the server needs no root privileges, so dropping
# them limits the blast radius of a compromise (#565). The app writes only to
# $HOME (config/cache/state), which is owned by this user.
RUN groupadd --system --gid 10001 friday_ai && \
    useradd --system --uid 10001 --gid friday_ai \
        --create-home --home-dir /home/friday_ai friday_ai
ENV HOME=/home/friday_ai
USER friday_ai

EXPOSE 8000

# Keep `friday` as the image entrypoint so Docker and Compose command overrides
# remain subcommands (for example, `docker run IMAGE serve ...`). Platforms
# such as Render replace CMD while preserving this entrypoint.
ENTRYPOINT ["friday"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
