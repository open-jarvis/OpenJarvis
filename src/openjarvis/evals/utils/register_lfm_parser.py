#!/usr/bin/env python3
"""
Runtime registration script for LFM custom tool parser.
This script monkey-patches vLLM to register the custom parser without file modifications.
"""

import sys
import os

# Add /tmp to path so we can import our custom parser
sys.path.insert(0, '/tmp')

# Import the custom parser
try:
    from lfm_custom_tool_parser import LFMToolParser
    print("✓ Successfully imported LFMToolParser")
except ImportError as e:
    print(f"✗ Failed to import LFMToolParser: {e}")
    sys.exit(1)

# Register with vLLM's ToolParserManager
try:
    from vllm.tool_parsers.abstract_tool_parser import ToolParserManager

    # Register our custom parser
    ToolParserManager.register_module("lfm_custom", LFMToolParser)
    print("✓ Successfully registered LFM parser as 'lfm_custom'")

    # Verify registration
    available_parsers = list(ToolParserManager.tool_parsers.keys()) + list(ToolParserManager.lazy_parsers.keys())
    print(f"\nAvailable parsers: {', '.join(sorted(available_parsers))}")

    # Try to get the parser to confirm it's registered
    parser_cls = ToolParserManager.get_tool_parser("lfm_custom")
    print(f"✓ Retrieved parser class: {parser_cls.__name__}")

    print("\n" + "="*60)
    print("SUCCESS: LFM custom parser is now registered!")
    print("="*60)
    print("\nTo use it, restart vLLM with:")
    print("  --tool-call-parser lfm_custom")
    print("\nOr modify the startup command to use 'lfm_custom' instead of 'pythonic'")

except Exception as e:
    print(f"✗ Failed to register parser: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
