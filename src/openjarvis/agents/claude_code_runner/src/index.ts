/**
 * OpenJarvis Claude Code Runner
 *
 * Reads a JSON request from stdin, invokes the Claude Agent SDK,
 * and writes sentinel-wrapped JSON output to stdout.
 *
 * Input (JSON on stdin):
 *   { prompt, api_key, workspace, allowed_tools, system_prompt, session_id }
 *
 * Output (on stdout, between sentinels):
 *   ---OPENJARVIS_OUTPUT_START---
 *   { content, tool_results, metadata }
 *   ---OPENJARVIS_OUTPUT_END---
 */

import { query } from "@anthropic-ai/claude-agent-sdk";

const OUTPUT_START = "---OPENJARVIS_OUTPUT_START---";
const OUTPUT_END = "---OPENJARVIS_OUTPUT_END---";

interface RunnerRequest {
  prompt: string;
  api_key: string;
  workspace: string;
  allowed_tools: string[];
  system_prompt: string;
  session_id: string;
}

interface ToolResultEntry {
  tool_name: string;
  content: string;
  success: boolean;
}

interface RunnerResponse {
  content: string;
  tool_results: ToolResultEntry[];
  metadata: Record<string, unknown>;
}

function emitResult(response: RunnerResponse): void {
  console.log(OUTPUT_START);
  console.log(JSON.stringify(response));
  console.log(OUTPUT_END);
}

function emitError(message: string): void {
  emitResult({
    content: message,
    tool_results: [],
    metadata: { error: true },
  });
}

async function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf-8");
    process.stdin.on("data", (chunk: string) => {
      data += chunk;
    });
    process.stdin.on("end", () => {
      resolve(data);
    });
    process.stdin.on("error", (err: Error) => {
      reject(err);
    });
  });
}

async function main(): Promise<void> {
  let request: RunnerRequest;

  try {
    const raw = await readStdin();
    request = JSON.parse(raw) as RunnerRequest;
  } catch (err) {
    emitError(`Failed to parse input: ${err}`);
    process.exit(1);
    return;
  }

  // Auth: forward an explicit API key only when one was actually given.
  // Otherwise strip any ambient ANTHROPIC_API_KEY from the child's env so
  // the SDK falls back to the stored `claude login` session (Pro/Max
  // subscription billing) instead of silently billing metered API credits.
  const env: Record<string, string | undefined> = { ...process.env };
  if (request.api_key) {
    env.ANTHROPIC_API_KEY = request.api_key;
  } else {
    delete env.ANTHROPIC_API_KEY;
  }

  let content = "";
  const toolResults: ToolResultEntry[] = [];
  const toolUseIdToIndex = new Map<string, number>();
  let isError = false;
  let resultMetadata: Record<string, unknown> = {};

  try {
    const stream = query({
      prompt: request.prompt,
      options: {
        cwd: request.workspace || undefined,
        systemPrompt: request.system_prompt || undefined,
        allowedTools: request.allowed_tools?.length
          ? request.allowed_tools
          : undefined,
        resume: request.session_id || undefined,
        maxTurns: 30,
        env,
      },
    });

    for await (const msg of stream) {
      if (msg.type === "assistant") {
        for (const block of msg.message.content) {
          if (block.type === "text") {
            content = block.text;
          } else if (block.type === "tool_use") {
            toolResults.push({
              tool_name: block.name,
              content: JSON.stringify(block.input),
              success: true,
            });
            toolUseIdToIndex.set(block.id, toolResults.length - 1);
          }
        }
      } else if (msg.type === "user") {
        const blocks = Array.isArray(msg.message.content)
          ? msg.message.content
          : [];
        for (const block of blocks) {
          if (block.type === "tool_result") {
            const idx = toolUseIdToIndex.get(block.tool_use_id);
            if (idx !== undefined) {
              const entry = toolResults[idx];
              entry.content =
                typeof block.content === "string"
                  ? block.content
                  : JSON.stringify(block.content);
              entry.success = !block.is_error;
            }
          }
        }
      } else if (msg.type === "result") {
        isError = msg.is_error;
        if (msg.subtype === "success") {
          content = msg.result || content;
        }
        resultMetadata = {
          session_id: msg.session_id,
          num_turns: msg.num_turns,
          total_cost_usd: msg.total_cost_usd,
        };
      }
    }

    emitResult({
      content,
      tool_results: toolResults,
      metadata: { ...resultMetadata, error: isError || undefined },
    });
    if (isError) process.exit(1);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    emitError(`Claude Code SDK error: ${message}`);
    process.exit(1);
  }
}

main();
