// src/openjarvis/evals/backends/external/_runners/openclaw_runner.mjs
// Subprocess bridge: runs one task through OpenClaw and emits JSON.
//
// Invoked as:
//   node openclaw_runner.mjs \
//     --task <prompt> --model <m> --base-url <url> --api-key <k> \
//     --output-json <path> [--workspace <path>]
//
// Loads OpenClaw from $OPENCLAW_PATH and runs `openclaw chat --message <task> --json`
// (or equivalent non-interactive entry). Emits a JSON dict matching the
// _RunnerOutput Pydantic schema in _subprocess_runner.py.

import { writeFileSync, existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { argv, env, exit, chdir } from 'node:process';

function parseArgs(args) {
  const out = {};
  for (let i = 2; i < args.length; i += 2) {
    const key = args[i].replace(/^--/, '').replace(/-/g, '_');
    out[key] = args[i + 1];
  }
  return out;
}

async function main() {
  const args = parseArgs(argv);
  const output = {
    content: '', usage: {}, trajectory: [],
    tool_calls: 0, turn_count: 0, error: null,
  };

  const openclawPath = env.OPENCLAW_PATH;
  if (!openclawPath) {
    output.error = 'OPENCLAW_PATH not set';
    writeFileSync(args.output_json, JSON.stringify(output));
    return 2;
  }

  if (args.workspace) chdir(args.workspace);

  const openclawBin = join(openclawPath, 'openclaw.mjs');
  if (!existsSync(openclawBin)) {
    output.error = `openclaw entry not found: ${openclawBin}`;
    writeFileSync(args.output_json, JSON.stringify(output));
    return 3;
  }

  const childEnv = {
    ...env,
    OPENCLAW_MODEL: args.model,
    OPENCLAW_BASE_URL: args.base_url,
    OPENCLAW_API_KEY: args.api_key,
  };

  // Use the SAME node executable that's running this script — picking up
  // 'node' from PATH can resolve to a system Node too old for OpenClaw
  // (which uses top-level await, requiring Node >=14.8).
  const nodeExe = process.execPath;

  // Use `openclaw agent --local` for headless single-shot invocation:
  // runs the embedded agent locally without going through the Gateway,
  // emits JSON. A unique --session-id per invocation gives each task a
  // fresh OpenClaw session (no carryover between eval tasks).
  const sessionId = (
    `openjarvis-eval-${Date.now()}-` +
    Math.floor(Math.random() * 1e9).toString(36)
  );
  const child = spawn(nodeExe, [
    openclawBin, 'agent',
    '--local',
    '--session-id', sessionId,
    '--message', args.task,
    '--json',
  ], { env: childEnv });

  let stdout = '';
  let stderr = '';
  child.stdout.on('data', (d) => { stdout += d.toString(); });
  child.stderr.on('data', (d) => { stderr += d.toString(); });

  const exitCode = await new Promise((resolve) => {
    child.on('close', resolve);
  });

  if (exitCode !== 0) {
    output.error = `openclaw_exit_${exitCode}: ${stderr.slice(-500)}`;
    writeFileSync(args.output_json, JSON.stringify(output));
    return exitCode;
  }

  // Parse OpenClaw's JSON output. Schema (provisional, validated against
  // OpenClaw's actual --json output during integration tests):
  //   { response: str, usage: {...}, messages: [{...}], tool_calls: int }
  try {
    const parsed = JSON.parse(stdout);
    output.content = parsed.response || '';
    output.usage = parsed.usage || {};
    output.trajectory = parsed.messages || [];
    output.tool_calls = parsed.tool_calls || 0;
    output.turn_count = (parsed.messages || []).filter(
      (m) => m.role === 'assistant'
    ).length;
  } catch (e) {
    output.error = `openclaw_output_parse_failed: ${e.message}`;
  }

  writeFileSync(args.output_json, JSON.stringify(output));
  return 0;
}

main().then(exit).catch((e) => {
  console.error(e);
  exit(1);
});
