CREATE TABLE submissions (
  id          BIGSERIAL PRIMARY KEY,
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Identity
  contributor TEXT NOT NULL,
  model       TEXT NOT NULL,
  hardware    TEXT NOT NULL,
  engine      TEXT NOT NULL,
  preset      TEXT,

  -- Intelligence Per Watt metrics
  task                TEXT    NOT NULL,
  accuracy            DOUBLE PRECISION NOT NULL CHECK (accuracy >= 0 AND accuracy <= 1),
  joules_per_query    DOUBLE PRECISION NOT NULL CHECK (joules_per_query > 0),
  latency_ms          DOUBLE PRECISION NOT NULL CHECK (latency_ms > 0),
  flops_per_query     DOUBLE PRECISION,
  dollars_per_query   DOUBLE PRECISION,

  -- Provenance
  trace_url   TEXT,
  commit_sha  TEXT
);

CREATE INDEX idx_submissions_task_score
  ON submissions (task, (accuracy / joules_per_query) DESC);

CREATE INDEX idx_submissions_submitted_at
  ON submissions (submitted_at DESC);
