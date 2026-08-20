/**
 * OpenJarvis Claude Agent SDK runner.
 *
 * Reads one JSON request from stdin and writes one sentinel-delimited JSON
 * response to stdout. The Python parent owns process timeouts and lifecycle.
 */

import { query } from "@anthropic-ai/claude-agent-sdk";

const OUTPUT_START = "---OPENJARVIS_OUTPUT_START---";
const OUTPUT_END = "---OPENJARVIS_OUTPUT_END---";

function emitResult(response) {
  console.log(OUTPUT_START);
  console.log(JSON.stringify(response));
  console.log(OUTPUT_END);
}

function emitError(message, metadata = {}) {
  emitResult({
    content: message,
    tool_results: [],
    metadata: { ...metadata, error: true },
  });
  console.error(message);
}

async function readStdin() {
  let data = "";
  process.stdin.setEncoding("utf-8");
  for await (const chunk of process.stdin) {
    data += chunk;
  }
  return data;
}

function serializeContent(content) {
  if (typeof content === "string") {
    return content;
  }
  return JSON.stringify(content ?? "");
}

function toolNameFromRule(rule) {
  const parenthesis = rule.indexOf("(");
  return (parenthesis === -1 ? rule : rule.slice(0, parenthesis)).trim();
}

async function main() {
  let request;
  try {
    request = JSON.parse(await readStdin());
  } catch (error) {
    emitError(`Failed to parse input: ${error}`);
    process.exitCode = 1;
    return;
  }

  const env = {
    ...process.env,
    CLAUDE_AGENT_SDK_CLIENT_APP: "openjarvis",
  };
  if (request.api_key) {
    env.ANTHROPIC_API_KEY = request.api_key;
  }

  const options = {
    maxTurns: 30,
    env,
    systemPrompt: request.system_prompt
      ? {
          type: "preset",
          preset: "claude_code",
          append: request.system_prompt,
        }
      : { type: "preset", preset: "claude_code" },
  };

  if (request.workspace) {
    options.cwd = request.workspace;
  }
  if (Array.isArray(request.allowed_tools)) {
    const allowedTools = request.allowed_tools.filter(
      (tool) => typeof tool === "string",
    );
    options.tools = [...new Set(allowedTools.map(toolNameFromRule).filter(Boolean))];
    if (allowedTools.length) {
      options.allowedTools = allowedTools;
    }
  }
  if (request.session_id) {
    options.resume = request.session_id;
  }

  const assistantText = [];
  const toolResults = [];
  const toolUseIndexes = new Map();
  let content = "";
  let messageCount = 0;
  let resultMetadata = {};
  let resultError = "";

  try {
    for await (const message of query({ prompt: request.prompt, options })) {
      messageCount += 1;

      if (message.type === "assistant") {
        const blocks = Array.isArray(message.message?.content)
          ? message.message.content
          : [];
        for (const block of blocks) {
          if (block.type === "text") {
            assistantText.push(block.text);
          } else if (block.type === "tool_use") {
            toolUseIndexes.set(block.id, toolResults.length);
            toolResults.push({
              tool_name: block.name,
              content: serializeContent(block.input),
              success: false,
            });
          }
        }
      } else if (message.type === "user") {
        const blocks = Array.isArray(message.message?.content)
          ? message.message.content
          : [];
        for (const block of blocks) {
          if (block.type !== "tool_result") {
            continue;
          }
          const index = toolUseIndexes.get(block.tool_use_id);
          if (index !== undefined) {
            toolResults[index].content = serializeContent(block.content);
            toolResults[index].success = !block.is_error;
          }
        }
      } else if (message.type === "result") {
        const permissionDenials = Array.isArray(message.permission_denials)
          ? message.permission_denials
          : [];
        for (const denial of permissionDenials) {
          const index = toolUseIndexes.get(denial.tool_use_id);
          if (index !== undefined) {
            toolResults[index].success = false;
            toolResults[index].content = `Permission denied: ${denial.tool_name}`;
          }
        }
        resultMetadata = {
          session_id: message.session_id,
          result_subtype: message.subtype,
          duration_ms: message.duration_ms,
          duration_api_ms: message.duration_api_ms,
          num_turns: message.num_turns,
          total_cost_usd: message.total_cost_usd,
          stop_reason: message.stop_reason,
          permission_denials: permissionDenials,
          error: message.is_error || undefined,
        };

        if (message.subtype === "success") {
          content = message.result || assistantText.join("\n");
        } else {
          resultError = Array.isArray(message.errors)
            ? message.errors.join("\n")
            : "";
          content = resultError || assistantText.join("\n");
        }
      }
    }

    content ||= assistantText.join("\n");
    emitResult({
      content,
      tool_results: toolResults,
      metadata: { ...resultMetadata, message_count: messageCount },
    });

    if (resultMetadata.error) {
      console.error(resultError || content || "Claude Agent SDK query failed.");
      process.exitCode = 1;
    }
  } catch (error) {
    const thrownMessage = error instanceof Error ? error.message : String(error);
    const message = resultError || `Claude Agent SDK error: ${thrownMessage}`;
    emitResult({
      content: message,
      tool_results: toolResults,
      metadata: {
        ...resultMetadata,
        message_count: messageCount,
        error: true,
      },
    });
    console.error(message);
    process.exitCode = 1;
  }
}

await main();
