# SPDX-License-Identifier: Apache-2.0
# Custom tool parser for LiquidAI LFM models
# Format: <|tool_call_start|>[function_name(arg1=val1, arg2=val2)]<|tool_call_end|>

import ast
import json
import re
from collections.abc import Sequence
from typing import Optional

from vllm.entrypoints.openai.chat_completion.protocol import (
    ChatCompletionRequest,
)
from vllm.entrypoints.openai.engine.protocol import (
    DeltaMessage,
    ExtractedToolCallInformation,
    FunctionCall,
    ToolCall,
)
from vllm.logger import init_logger
from vllm.tool_parsers.abstract_tool_parser import (
    Tool,
    ToolParser,
)
from vllm.entrypoints.chat_utils import make_tool_call_id

logger = init_logger(__name__)


class LFMToolParser(ToolParser):
    """
    Tool call parser for LiquidAI LFM models that produce tool calls in format:
    <|tool_call_start|>[function_name(arg1=val1, arg2=val2)]<|tool_call_end|>
    """

    TOOL_CALL_START_TAG = "<|tool_call_start|>"
    TOOL_CALL_END_TAG = "<|tool_call_end|>"

    # Regex to match tool calls with the custom format
    TOOL_CALL_REGEX = re.compile(
        r'<\|tool_call_start\|\>\[(.*?)\]<\|tool_call_end\|\>',
        re.DOTALL
    )

    def __init__(self, tokenizer, tools: list[Tool] | None = None):
        super().__init__(tokenizer, tools)

    def extract_tool_calls(
        self, model_output: str, request: ChatCompletionRequest
    ) -> ExtractedToolCallInformation:
        """
        Extract tool calls from a complete model response.

        Expected format: <|tool_call_start|>[func1(...), func2(...)]<|tool_call_end|>
        or: <|tool_call_start|>[func(...)]<|tool_call_end|>
        """
        # Quick check if tool call tags are present
        if self.TOOL_CALL_START_TAG not in model_output:
            return ExtractedToolCallInformation(
                tools_called=False, tool_calls=[], content=model_output
            )

        try:
            # Find all tool call blocks
            matches = self.TOOL_CALL_REGEX.findall(model_output)

            if not matches:
                return ExtractedToolCallInformation(
                    tools_called=False, tool_calls=[], content=model_output
                )

            tool_calls = []

            for match in matches:
                # Parse the pythonic function call(s) inside the brackets
                # match contains: "func1(...), func2(...)" or "func(...)"
                function_text = match.strip()

                # Try to parse as Python AST
                try:
                    # Wrap in brackets if not already a list
                    if not function_text.startswith('['):
                        function_text = f'[{function_text}]'

                    module = ast.parse(function_text)
                    parsed = getattr(module.body[0], "value", None)

                    if isinstance(parsed, ast.List):
                        calls = parsed.elts
                    elif isinstance(parsed, ast.Call):
                        calls = [parsed]
                    else:
                        logger.warning(f"Unexpected AST type: {type(parsed)}")
                        continue

                    # Process each function call
                    for call in calls:
                        if not isinstance(call, ast.Call):
                            continue

                        func_name = self._get_function_name(call)
                        arguments = self._extract_arguments(call)

                        tool_call = ToolCall(
                            type="function",
                            function=FunctionCall(
                                name=func_name,
                                arguments=json.dumps(arguments, ensure_ascii=False)
                            )
                        )
                        tool_calls.append(tool_call)

                except Exception as e:
                    logger.warning(f"Failed to parse tool call: {function_text}. Error: {e}")
                    continue

            if tool_calls:
                # Remove tool call tags from content
                remaining_content = self.TOOL_CALL_REGEX.sub('', model_output).strip()
                if not remaining_content:
                    remaining_content = None

                return ExtractedToolCallInformation(
                    tools_called=True,
                    tool_calls=tool_calls,
                    content=remaining_content
                )
            else:
                return ExtractedToolCallInformation(
                    tools_called=False, tool_calls=[], content=model_output
                )

        except Exception as e:
            logger.exception(f"Error in extracting tool call from response: {e}")
            return ExtractedToolCallInformation(
                tools_called=False, tool_calls=[], content=model_output
            )

    def extract_tool_calls_streaming(
        self,
        previous_text: str,
        current_text: str,
        delta_text: str,
        previous_token_ids: Sequence[int],
        current_token_ids: Sequence[int],
        delta_token_ids: Sequence[int],
        request: ChatCompletionRequest,
    ) -> DeltaMessage | None:
        """
        Extract tool calls from streaming response.
        For simplicity, return content until tool call is complete.
        """
        # If we haven't seen the start tag yet, just stream content
        if self.TOOL_CALL_START_TAG not in current_text:
            return DeltaMessage(content=delta_text)

        # If tool call is incomplete (no end tag yet), hold off on streaming
        if self.TOOL_CALL_START_TAG in current_text and self.TOOL_CALL_END_TAG not in current_text:
            return None

        # Tool call is complete, extract it
        extracted = self.extract_tool_calls(current_text, request)

        if extracted.tools_called and extracted.tool_calls:
            # Return tool calls on first detection
            if not self.prev_tool_call_arr:
                self.prev_tool_call_arr = extracted.tool_calls
                from vllm.entrypoints.openai.engine.protocol import DeltaFunctionCall, DeltaToolCall

                deltas = []
                for idx, tool_call in enumerate(extracted.tool_calls):
                    delta = DeltaToolCall(
                        index=idx,
                        type="function",
                        id=make_tool_call_id("random", tool_call.function.name, idx),
                        function=DeltaFunctionCall(
                            name=tool_call.function.name,
                            arguments=tool_call.function.arguments
                        )
                    )
                    deltas.append(delta)

                return DeltaMessage(tool_calls=deltas)
            else:
                # Already sent tool calls
                return DeltaMessage(content="")

        # No tool calls, stream content
        return DeltaMessage(content=delta_text)

    def _get_function_name(self, call: ast.Call) -> str:
        """Extract function name from AST Call node."""
        if isinstance(call.func, ast.Name):
            return call.func.id
        elif isinstance(call.func, ast.Attribute):
            return call.func.attr
        else:
            return str(call.func)

    def _extract_arguments(self, call: ast.Call) -> dict:
        """Extract arguments from AST Call node and convert to dict."""
        arguments = {}

        # Handle keyword arguments
        for keyword in call.keywords:
            arg_name = keyword.arg
            arg_value = self._eval_ast_node(keyword.value)
            if arg_name:
                arguments[arg_name] = arg_value

        # Handle positional arguments (if any)
        for idx, arg in enumerate(call.args):
            arg_value = self._eval_ast_node(arg)
            arguments[f"arg{idx}"] = arg_value

        return arguments

    def _eval_ast_node(self, node):
        """Safely evaluate AST node to Python value."""
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError):
            # If literal_eval fails, return string representation
            if isinstance(node, ast.Name):
                return node.id
            elif isinstance(node, ast.Attribute):
                return f"{self._eval_ast_node(node.value)}.{node.attr}"
            elif isinstance(node, ast.Call):
                # Nested function call - return as string
                return ast.unparse(node)
            else:
                return ast.unparse(node)


# Register the parser
def register_lfm_parser():
    """Register the LFM parser with vLLM's ToolParserManager."""
    try:
        from vllm.tool_parsers.abstract_tool_parser import ToolParserManager
        ToolParserManager.register_module("lfm_custom", LFMToolParser)
        logger.info("Successfully registered LFM custom tool parser as 'lfm_custom'")
        return True
    except Exception as e:
        logger.error(f"Failed to register LFM parser: {e}")
        return False


if __name__ == "__main__":
    # Quick test
    test_output = '<|tool_call_start|>[web_search(query="GitLab CFO April 2026", max_results=3)]<|tool_call_end|>I will search for information.'

    class MockTokenizer:
        def get_vocab(self):
            return {}

    parser = LFMToolParser(MockTokenizer())
    result = parser.extract_tool_calls(test_output, None)

    print("Test extraction:")
    print(f"Tools called: {result.tools_called}")
    print(f"Number of tool calls: {len(result.tool_calls)}")
    if result.tool_calls:
        for tc in result.tool_calls:
            print(f"  Function: {tc.function.name}")
            print(f"  Arguments: {tc.function.arguments}")
    print(f"Remaining content: {result.content}")
