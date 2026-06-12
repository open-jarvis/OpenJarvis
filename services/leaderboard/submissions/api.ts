import { api, APIError } from "encore.dev/api";
import { CronJob } from "encore.dev/cron";
import {
  CacheCluster,
  IntKeyspace,
  expireIn,
} from "encore.dev/storage/cache";
import { db } from "./db";

interface SubmitRequest {
  contributor: string;
  model: string;
  hardware: string;
  engine: "ollama" | "vllm" | "sglang" | "llama.cpp" | "cloud";
  preset?: string;
  task: string;
  accuracy: number;
  joulesPerQuery: number;
  latencyMs: number;
  flopsPerQuery?: number;
  dollarsPerQuery?: number;
  traceUrl?: string;
  commitSha?: string;
}

interface SubmitResponse {
  id: number;
  intelligencePerWatt: number;
}

interface LeaderboardEntry {
  id: number;
  contributor: string;
  model: string;
  hardware: string;
  engine: string;
  task: string;
  accuracy: number;
  joulesPerQuery: number;
  intelligencePerWatt: number;
  submittedAt: Date;
}

interface LeaderboardResponse {
  task: string;
  entries: LeaderboardEntry[];
  refreshedAt: Date;
}

const cluster = new CacheCluster("ratelimit", {
  evictionPolicy: "allkeys-lru",
});

const submitsPerHour = new IntKeyspace<{ contributor: string }>(cluster, {
  keyPattern: "submits/:contributor",
  defaultExpiry: expireIn(60 * 60 * 1000),
});

const SUBMIT_LIMIT_PER_HOUR = 30;

export const submit = api(
  { expose: true, method: "POST", path: "/submissions" },
  async (req: SubmitRequest): Promise<SubmitResponse> => {
    if (req.accuracy < 0 || req.accuracy > 1) {
      throw APIError.invalidArgument("accuracy must be in [0, 1]");
    }
    if (req.joulesPerQuery <= 0) {
      throw APIError.invalidArgument("joulesPerQuery must be > 0");
    }

    const count = await submitsPerHour.increment(
      { contributor: req.contributor },
      1,
    );
    if (count > SUBMIT_LIMIT_PER_HOUR) {
      throw APIError.resourceExhausted(
        `rate limit: ${SUBMIT_LIMIT_PER_HOUR} submissions/hour`,
      );
    }

    const row = await db.queryRow<{ id: number }>`
      INSERT INTO submissions (
        contributor, model, hardware, engine, preset,
        task, accuracy, joules_per_query, latency_ms,
        flops_per_query, dollars_per_query,
        trace_url, commit_sha
      ) VALUES (
        ${req.contributor}, ${req.model}, ${req.hardware}, ${req.engine}, ${req.preset ?? null},
        ${req.task}, ${req.accuracy}, ${req.joulesPerQuery}, ${req.latencyMs},
        ${req.flopsPerQuery ?? null}, ${req.dollarsPerQuery ?? null},
        ${req.traceUrl ?? null}, ${req.commitSha ?? null}
      )
      RETURNING id
    `;

    if (!row) {
      throw APIError.internal("failed to insert submission");
    }

    return {
      id: row.id,
      intelligencePerWatt: req.accuracy / req.joulesPerQuery,
    };
  },
);

interface ListParams {
  task: string;
  limit?: number;
}

export const list = api(
  { expose: true, method: "GET", path: "/leaderboard/:task" },
  async ({ task, limit }: ListParams): Promise<LeaderboardResponse> => {
    const cap = Math.min(Math.max(limit ?? 25, 1), 100);

    const entries: LeaderboardEntry[] = [];
    for await (const r of db.query<{
      id: number;
      contributor: string;
      model: string;
      hardware: string;
      engine: string;
      task: string;
      accuracy: number;
      joules_per_query: number;
      submitted_at: Date;
    }>`
      SELECT id, contributor, model, hardware, engine, task,
             accuracy, joules_per_query, submitted_at
      FROM submissions
      WHERE task = ${task}
      ORDER BY accuracy / joules_per_query DESC
      LIMIT ${cap}
    `) {
      entries.push({
        id: r.id,
        contributor: r.contributor,
        model: r.model,
        hardware: r.hardware,
        engine: r.engine,
        task: r.task,
        accuracy: r.accuracy,
        joulesPerQuery: r.joules_per_query,
        intelligencePerWatt: r.accuracy / r.joules_per_query,
        submittedAt: r.submitted_at,
      });
    }

    return { task, entries, refreshedAt: new Date() };
  },
);

export const refreshAggregates = api(
  { expose: false, method: "POST", path: "/internal/refresh" },
  async (): Promise<{ tasks: number }> => {
    const row = await db.queryRow<{ tasks: number }>`
      SELECT COUNT(DISTINCT task)::int AS tasks FROM submissions
    `;
    return { tasks: row?.tasks ?? 0 };
  },
);

const _refreshNightly = new CronJob("refresh-leaderboard", {
  title: "Recompute leaderboard aggregates",
  every: "1h",
  endpoint: refreshAggregates,
});
