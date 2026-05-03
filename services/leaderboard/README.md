# OpenJarvis Leaderboard Service

A small Encore.ts backend that accepts Intelligence Per Watt benchmark submissions
from `jarvis bench` runs and serves the public leaderboard at
[open-jarvis.github.io/OpenJarvis/leaderboard](https://open-jarvis.github.io/OpenJarvis/leaderboard/).

This service is intentionally isolated from the local-first OpenJarvis runtime
(`src/openjarvis/`). It only exists to power the *public* leaderboard surface.

## Local development

```bash
cd services/leaderboard
npm install
encore run
```

Encore provisions PostgreSQL and Redis in Docker automatically and applies the
migration in `submissions/migrations/`. The local dev dashboard at
<http://localhost:9400> shows API docs, traces, and a SQL console.

## Endpoints

| Method | Path                      | Purpose                                |
|--------|---------------------------|----------------------------------------|
| POST   | `/submissions`            | Submit a benchmark result (rate-limited: 30/hr/contributor) |
| GET    | `/leaderboard/:task`      | Top-N entries ranked by accuracy / J   |

A cron job recomputes aggregates every hour.

## Submitting from `jarvis bench`

```bash
curl -X POST http://localhost:4000/submissions \
  -H 'Content-Type: application/json' \
  -d '{
    "contributor": "lissa",
    "model": "qwen3.5:4b",
    "hardware": "M3 Max 64GB",
    "engine": "ollama",
    "task": "mmlu-sample",
    "accuracy": 0.62,
    "joulesPerQuery": 18.4,
    "latencyMs": 1240,
    "commitSha": "'$(git -C ../.. rev-parse HEAD)'"
  }'
```

## Deploy

- **Encore Cloud** (zero-config GCP/AWS): `git push encore`
- **Self-host**: `encore build docker leaderboard:latest && docker run ...`
