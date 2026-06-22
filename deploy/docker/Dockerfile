# Base images are pinned to an immutable digest (in addition to a human-readable
# tag) so every build resolves the exact same layers — reproducible builds and
# safe rollbacks (#563).

# Stage 1: Build frontend SPA
FROM node:22.23.0-slim@sha256:d9f850096136edbc402debdd8729579a288aac64574ada0ff4db26b6ae58b0b2 AS frontend

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install
COPY frontend/ .
RUN npm run build

# Stage 2: Build Python package
FROM python:3.12.13-slim-bookworm@sha256:76d4b7b6305788c6b4c6a19d6a22a3921bf802e9af4d5e1e5bd771208dba74bf AS builder

WORKDIR /app

# Install dependencies from the committed lockfile (#567). `uv export --frozen`
# reads uv.lock as-is (no re-resolution) and emits a fully pinned, hash-verified
# requirements set; `--no-deps` then installs exactly that set. This is a
# separate layer from the source copy so dependency installs stay cached when
# only application code changes.
COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv && \
    uv export --frozen --no-dev --extra server --no-emit-project > requirements.txt && \
    uv pip install --system --no-deps -r requirements.txt

# Copy the source and the non-src force-include paths (see pyproject
# [tool.hatch.build.targets.wheel.force-include]) before building the project.
COPY src/ src/
COPY scripts/install scripts/install
COPY deploy/windows deploy/windows

# Copy built frontend into the server static directory
COPY --from=frontend /src/openjarvis/server/static src/openjarvis/server/static/

# Install the project itself without re-resolving dependencies.
RUN uv pip install --system --no-deps .

# Stage 3: Runtime
FROM python:3.12.13-slim-bookworm@sha256:76d4b7b6305788c6b4c6a19d6a22a3921bf802e9af4d5e1e5bd771208dba74bf

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
WORKDIR /app

# Run as an unprivileged user — the server needs no root privileges, so dropping
# them limits the blast radius of a compromise (#565). The app writes only to
# $HOME (config/cache/state), which is owned by this user.
RUN groupadd --system --gid 10001 openjarvis && \
    useradd --system --uid 10001 --gid openjarvis \
        --create-home --home-dir /home/openjarvis openjarvis
ENV HOME=/home/openjarvis
USER openjarvis

EXPOSE 8000

ENTRYPOINT ["jarvis"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
