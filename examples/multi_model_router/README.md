# Multi-Model Router

Route queries to the cheapest capable model using FridayAI's learning/routing
system. Simple queries go to small fast models; complex code or math queries go
to larger models.

## Requirements

- FridayAI installed (`git clone https://github.com/open-jarvis/FridayAI.git && cd FridayAI && uv sync` or `uv sync --extra dev`)
- An inference engine running with multiple models available

## Usage

```bash
python examples/multi_model_router/multi_model_router.py --help

# Simple query -> routes to smallest model
python examples/multi_model_router/multi_model_router.py --query "What is 2+2?"

# Complex reasoning -> routes to largest model
python examples/multi_model_router/multi_model_router.py \
    --query "Explain quantum entanglement step by step" --verbose

# Code query -> routes to code-specialized model
python examples/multi_model_router/multi_model_router.py \
    --query "def fibonacci(n):" --verbose

# Specify available models explicitly
python examples/multi_model_router/multi_model_router.py \
    --query "Summarize this paper" \
    --models "qwen3:0.6b,qwen3:8b,qwen3:32b"

# Use bandit (Thompson Sampling) strategy
python examples/multi_model_router/multi_model_router.py \
    --query "Solve the integral of x^2" --strategy bandit
```

## How It Works

The script uses FridayAI's routing infrastructure from the learning pillar:

- **HeuristicRouter** (default) -- rule-based routing that analyzes the query
  for code patterns, math keywords, length, and complexity to pick the right
  model tier. Short simple queries go to the smallest model; code and math
  queries go to larger or specialized models.

- **BanditRouterPolicy** -- Thompson Sampling multi-armed bandit that learns
  which model performs best for each query class over time.

Both routers use `build_routing_context()` to extract query features (length,
has_code, has_math) and then select from the available model pool. Use
`--verbose` to see the routing decision details.
