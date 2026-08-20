// src/openjarvis/evals/backends/external/_runners/openclaw_runner.mjs
// Subprocess bridge: runs one task through OpenClaw and emits JSON.
//
// Invoked as:
//   node openclaw_runner.mjs \
//     --task <prompt> --model <m> --base-url <url> --api-key <k> \
//     --output-json <path> [--workspace <path>]
//
// Loads OpenClaw from $OPENCLAW_PATH and runs `openclaw agent --local
// --message <task> --json`. Emits a JSON dict matching the
// _RunnerOutput Pydantic schema in _subprocess_runner.py.

import { mkdtempSync, writeFileSync, existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
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

  const requestedModel = String(args.model || '').includes('/')
    ? String(args.model || '')
    : `ollama/${args.model}`;
  const runDir = mkdtempSync(join(tmpdir(), 'openjarvis-openclaw-'));
  const configPath = join(runDir, 'openclaw.json');
  writeFileSync(configPath, JSON.stringify({
    agents: {
      defaults: {
        model: { primary: requestedModel },
        models: { [requestedModel]: {} },
      },
    },
  }));

  const childEnv = {
    ...env,
    OPENCLAW_MODEL: args.model,
    OPENCLAW_BASE_URL: args.base_url,
    OPENCLAW_API_KEY: args.api_key,
    OPENCLAW_CONFIG_PATH: configPath,
  };
  if (requestedModel.startsWith('ollama/')) {
    childEnv.OLLAMA_API_KEY = args.api_key || 'ollama';
  }

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
    const payloads = Array.isArray(parsed.payloads) ? parsed.payloads : [];
    const messages = Array.isArray(parsed.messages) ? parsed.messages : [];
    const usage = parsed.usage || parsed.meta?.agentMeta?.usage || {};
    output.content = parsed.response || payloads.map((p) => p.text || '').join('\n');
    output.usage = {
      prompt_tokens: usage.prompt_tokens ?? usage.input ?? 0,
      completion_tokens: usage.completion_tokens ?? usage.output ?? 0,
      total_tokens: usage.total_tokens ?? usage.total ?? 0,
    };
    output.trajectory = messages;
    output.tool_calls = parsed.tool_calls || 0;
    output.turn_count = messages.filter(
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
