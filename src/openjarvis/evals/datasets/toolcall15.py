"""ToolCall-15 dataset provider — lightweight tool calling benchmark.

Provides 15 scenarios across 5 categories (3 per category) that test
whether a model can call the right tool with the right arguments.

Reference: https://github.com/stevibe/ToolCall-15
"""

from __future__ import annotations

import json
import logging
import random
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Universal system prompt (from METHODOLOGY.md)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a helpful assistant with access to the tools provided.\n\n"
    "Rules:\n"
    "- Use a tool ONLY when necessary to fulfill the user's request.\n"
    "- Answer directly from knowledge without tool calls when possible.\n"
    "- If a tool call fails, explain the failure and suggest alternatives.\n"
    "- Never invent information that a tool should provide."
)

# ---------------------------------------------------------------------------
# 12-tool universal toolkit (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a specific location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or location name",
                    },
                    "units": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "default": "celsius",
                        "description": "Temperature units",
                    },
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Perform mathematical calculations",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Math expression to evaluate",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email to a recipient",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address",
                    },
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body"},
                    "attachments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": "File paths to attach",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files by name or content",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "file_type": {
                        "type": "string",
                        "enum": ["pdf", "docx", "xlsx", "any"],
                        "default": "any",
                        "description": "File type filter",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a specific file",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "File identifier",
                    },
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a new calendar event",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title"},
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format",
                    },
                    "time": {
                        "type": "string",
                        "description": "Time in HH:MM format",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "default": 60,
                        "description": "Duration in minutes",
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": "Attendee emails",
                    },
                },
                "required": ["title", "date", "time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_contacts",
            "description": "Look up contacts by name or group",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Name or group to search",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "translate_text",
            "description": "Translate text from one language to another",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to translate"},
                    "source_language": {
                        "type": "string",
                        "description": "Source language",
                    },
                    "target_language": {
                        "type": "string",
                        "description": "Target language",
                    },
                },
                "required": ["text", "source_language", "target_language"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_price",
            "description": "Get current stock price for a ticker symbol",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol",
                    },
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Set a reminder for a future time",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Reminder message",
                    },
                    "datetime": {
                        "type": "string",
                        "description": "ISO 8601 datetime for the reminder",
                    },
                },
                "required": ["message", "datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_code",
            "description": "Execute a code snippet and return output",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript"],
                        "description": "Programming language",
                    },
                    "code": {
                        "type": "string",
                        "description": "Code to execute",
                    },
                },
                "required": ["language", "code"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# 15 scenarios
# ---------------------------------------------------------------------------

# Categories:
#   A = Tool Selection (TC-01..03)
#   B = Parameter Precision (TC-04..06)
#   C = Multi-Step Chains (TC-07..09)
#   D = Restraint & Refusal (TC-10..12)
#   E = Error Recovery (TC-13..15)

SCENARIOS: List[Dict[str, Any]] = [
    # --- Category A: Tool Selection ---
    {
        "id": "TC-01",
        "name": "Direct Specialist Match",
        "category": "A-ToolSelection",
        "user_message": "What's the weather like in Berlin right now?",
        "mock_tool_outputs": {
            "get_weather": json.dumps(
                {
                    "location": "Berlin",
                    "temperature": 8,
                    "units": "celsius",
                    "condition": "Overcast",
                    "humidity": 72,
                }
            ),
            "web_search": json.dumps(
                {"results": [{"snippet": "Berlin weather right now: 8C and overcast."}]}
            ),
        },
    },
    {
        "id": "TC-02",
        "name": "Distractor Resistance",
        "category": "A-ToolSelection",
        "user_message": "What is the current price of AAPL stock?",
        "mock_tool_outputs": {
            "get_stock_price": json.dumps(
                {
                    "ticker": "AAPL",
                    "price": 187.42,
                    "currency": "USD",
                    "change": "+1.23",
                    "change_percent": "+0.66%",
                }
            ),
            "web_search": json.dumps(
                {"results": [{"snippet": "AAPL is trading around $187.42."}]}
            ),
        },
    },
    {
        "id": "TC-03",
        "name": "Implicit Tool Need",
        "category": "A-ToolSelection",
        "user_message": "I need to let Sarah know the meeting moved to 3pm.",
        "mock_tool_outputs": {
            "get_contacts": json.dumps(
                {"results": [{"name": "Sarah Chen", "email": "sarah.chen@company.com"}]}
            ),
            "send_email": json.dumps(
                {
                    "status": "sent",
                    "message_id": "msg_8821",
                }
            ),
        },
    },
    # --- Category B: Parameter Precision ---
    {
        "id": "TC-04",
        "name": "Unit Handling",
        "category": "B-ParameterPrecision",
        "user_message": "What's the temperature in Tokyo in Fahrenheit?",
        "mock_tool_outputs": {
            "get_weather": json.dumps(
                {
                    "location": "Tokyo",
                    "temperature": 64,
                    "units": "fahrenheit",
                    "condition": "Clear",
                    "humidity": 55,
                }
            ),
            # Default (celsius) mock for partial-credit scoring
            "get_weather__default": json.dumps(
                {
                    "location": "Tokyo",
                    "temperature": 18,
                    "units": "celsius",
                    "condition": "Clear",
                    "humidity": 55,
                }
            ),
        },
    },
    {
        "id": "TC-05",
        "name": "Date and Time Parsing",
        "category": "B-ParameterPrecision",
        "user_message": (
            "Schedule a team standup for next Monday at 9:30am, "
            "30 minutes, with Alex and Jamie."
        ),
        "mock_tool_outputs": {
            "get_contacts": json.dumps(
                {
                    "results": [
                        {"name": "Alex Stone", "email": "alex.stone@company.com"},
                        {"name": "Jamie Liu", "email": "jamie.liu@company.com"},
                    ]
                }
            ),
            "create_calendar_event": json.dumps(
                {
                    "event_id": "evt_4412",
                    "status": "created",
                    "title": "Team Standup",
                    "date": "2026-03-23",
                }
            ),
        },
        # Reference date is 2026-03-20 (Friday), next Monday = 2026-03-23
        "reference_date": "2026-03-20",
    },
    {
        "id": "TC-06",
        "name": "Multi-Value Extraction",
        "category": "B-ParameterPrecision",
        "user_message": (
            "Translate 'Where is the nearest hospital?' "
            "from English to both Spanish and Japanese."
        ),
        "mock_tool_outputs": {
            "translate_text__spanish": json.dumps(
                {
                    "translated": "\u00bfD\u00f3nde est\u00e1 el hospital m\u00e1s cercano?",
                }
            ),
            "translate_text__japanese": json.dumps(
                {
                    "translated": "\u6700\u5bc4\u308a\u306e\u75c5\u9662\u306f\u3069\u3053\u3067\u3059\u304b\uff1f",
                }
            ),
        },
    },
    # --- Category C: Multi-Step Chains ---
    {
        "id": "TC-07",
        "name": "Search \u2192 Read \u2192 Act",
        "category": "C-MultiStepChains",
        "user_message": (
            "Find the Q3 budget report and email the total to my manager."
        ),
        "mock_tool_outputs": {
            "search_files": json.dumps(
                {
                    "results": [
                        {
                            "file_id": "file_091",
                            "name": "Q3_Budget_Report_2025.xlsx",
                        }
                    ]
                }
            ),
            "read_file": json.dumps(
                {
                    "content": (
                        "Department budgets: Engineering $2.1M, Marketing $800K, "
                        "Sales $1.5M. Total: $4.4M"
                    ),
                }
            ),
            "get_contacts": json.dumps(
                {
                    "results": [
                        {
                            "name": "Jordan Park",
                            "email": "jordan.park@company.com",
                            "role": "manager",
                        }
                    ]
                }
            ),
            "send_email": json.dumps({"status": "sent"}),
        },
    },
    {
        "id": "TC-08",
        "name": "Conditional Branching",
        "category": "C-MultiStepChains",
        "user_message": (
            "Check the weather in Paris. If it's raining, "
            "remind me to bring an umbrella tomorrow at 8am."
        ),
        "mock_tool_outputs": {
            "get_weather": json.dumps(
                {
                    "location": "Paris",
                    "temperature": 11,
                    "condition": "Light rain",
                    "humidity": 89,
                }
            ),
            "set_reminder": json.dumps(
                {
                    "reminder_id": "rem_553",
                    "status": "set",
                }
            ),
        },
        "reference_date": "2026-03-20",
    },
    {
        "id": "TC-09",
        "name": "Parallel Independence",
        "category": "C-MultiStepChains",
        "user_message": ("What's the weather in London and the stock price of MSFT?"),
        "mock_tool_outputs": {
            "get_weather": json.dumps(
                {
                    "location": "London",
                    "temperature": 12,
                    "condition": "Cloudy",
                }
            ),
            "get_stock_price": json.dumps(
                {
                    "ticker": "MSFT",
                    "price": 412.78,
                    "currency": "USD",
                }
            ),
            "web_search": json.dumps(
                {
                    "results": [
                        {
                            "snippet": (
                                "London is cloudy at 12C and MSFT is around $412.78."
                            )
                        }
                    ]
                }
            ),
        },
    },
    # --- Category D: Restraint & Refusal ---
    {
        "id": "TC-10",
        "name": "Trivial Knowledge",
        "category": "D-RestraintRefusal",
        "user_message": "What year did World War II end?",
        "mock_tool_outputs": {},
    },
    {
        "id": "TC-11",
        "name": "Simple Math",
        "category": "D-RestraintRefusal",
        "user_message": "What is 15% of 200?",
        "mock_tool_outputs": {
            "calculator": json.dumps({"result": 30}),
        },
    },
    {
        "id": "TC-12",
        "name": "Impossible Request",
        "category": "D-RestraintRefusal",
        "user_message": "Delete all my emails from last month.",
        "mock_tool_outputs": {},
    },
    # --- Category E: Error Recovery ---
    {
        "id": "TC-13",
        "name": "Empty Results",
        "category": "E-ErrorRecovery",
        "user_message": "Find the Johnson proposal document.",
        "mock_tool_outputs": {
            # First call returns empty, second (broader) returns a result
            "search_files__first": json.dumps({"results": []}),
            "search_files__retry": json.dumps(
                {
                    "results": [
                        {
                            "file_id": "file_117",
                            "name": "Johnson_Project_Proposal_v2.docx",
                        }
                    ]
                }
            ),
        },
    },
    {
        "id": "TC-14",
        "name": "Malformed Response",
        "category": "E-ErrorRecovery",
        "user_message": "What's Apple's stock price?",
        "mock_tool_outputs": {
            "get_stock_price": json.dumps(
                {
                    "error": "Service temporarily unavailable. Rate limit exceeded.",
                }
            ),
            "web_search": json.dumps(
                {"results": [{"snippet": "Apple (AAPL) is trading around $187.42."}]}
            ),
        },
    },
    {
        "id": "TC-15",
        "name": "Conflicting Information",
        "category": "E-ErrorRecovery",
        "user_message": (
            "Search for the population of Iceland and calculate what 2% of it would be."
        ),
        "mock_tool_outputs": {
            "web_search": json.dumps(
                {
                    "results": [
                        {
                            "snippet": (
                                "Iceland has a population of approximately "
                                "372,520 as of 2025."
                            )
                        }
                    ]
                }
            ),
            "calculator": json.dumps({"result": 7450.4}),
        },
    },
]


class ToolCall15Dataset(DatasetProvider):
    """ToolCall-15 tool calling benchmark.

    Provides 15 scenarios across 5 categories that test whether a model
    can call the right tool with the right arguments. All tool outputs
    are pre-defined (mocked) per the benchmark specification.
    """

    dataset_id = "toolcall15"
    dataset_name = "ToolCall-15"

    def __init__(self) -> None:
        self._records: List[EvalRecord] = []

    def verify_requirements(self) -> List[str]:
        return []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        scenarios = list(SCENARIOS)

        # Optional category filter via split (e.g. "A", "A,B", "D-RestraintRefusal")
        if split:
            filter_cats = [c.strip().upper() for c in split.split(",")]
            scenarios = [
                s
                for s in scenarios
                if any(s["category"].upper().startswith(fc) for fc in filter_cats)
            ]

        if seed is not None:
            random.Random(seed).shuffle(scenarios)
        if max_samples is not None:
            scenarios = scenarios[:max_samples]

        self._records = []
        for s in scenarios:
            # Build a self-contained prompt that includes the system
            # instructions, available tools, and user message so the
            # model can respond with tool calls via any backend.
            tool_descriptions = "\n".join(
                f"- {t['function']['name']}: {t['function']['description']}"
                for t in TOOLS
            )
            prompt = (
                f"{SYSTEM_PROMPT}\n\n"
                f"## Available Tools\n"
                f"{tool_descriptions}\n\n"
                f"When you need to use a tool, respond with ONLY "
                f"a JSON object in this format:\n"
                f'{{"tool": "<tool_name>", "arguments": {{...}}}}\n\n'
                f"If the task requires multiple tools, call them "
                f"one at a time. If no tool is needed, respond "
                f"directly with your answer.\n\n"
                f"## User Request\n{s['user_message']}"
            )
            self._records.append(
                EvalRecord(
                    record_id=s["id"],
                    problem=prompt,
                    reference="",
                    category=s["category"],
                    subject=s["name"],
                    metadata={
                        "system_prompt": SYSTEM_PROMPT,
                        "tools": TOOLS,
                        "mock_tool_outputs": s["mock_tool_outputs"],
                        "reference_date": s.get("reference_date"),
                        "scenario_id": s["id"],
                        "scenario_name": s["name"],
                    },
                )
            )

        LOGGER.info("ToolCall-15: loaded %d scenarios", len(self._records))

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["ToolCall15Dataset"]
