# LAR-1 Semantic Routing — OpenJarvis Skill

Route agent queries to the cheapest capable model using LAR-1 semantic metadata.
Reduces cloud API costs by 50%+ with no quality loss.

## Installation

```bash
jarvis skill install github:cloudiaspecula/OpenJarvis   --skills-dir skills/lar1-semantic-routing
```

## Quick Start

```python
from lar1_classifier import classify

meta = {"T": "now", "C": "obs", "E": "direct", "L": 0.99}
decision = classify(meta)
print(decision.route, decision.model_name)
# → local qwen2.5-7b
```

## How It Works

8 priority-ordered rules map LAR-1 dimensions to routing decisions:

| Rule | Condition | Route | Model |
|------|-----------|-------|-------|
| 1 | L < 0.3 | cloud | gpt-4o (premium) |
| 2 | C=unc | cloud | gpt-4o (premium) |
| 3 | E=speculative | cloud | gpt-4o-mini |
| 4 | T=recall | cloud | gpt-4o |
| 5 | C=exp | cloud | gpt-4o-mini |
| 6 | L≥0.7 + C∈{obs,dec} | local | qwen2.5-7b |
| 7 | C=meta | local | qwen2.5-7b |
| 8 | default | local | qwen2.5-7b |

## Run Demo

```bash
python3 examples/openjarvis_lar1_example.py
```

Takes ~1 second, no API keys needed.

## Integration with HeuristicRouter

In OpenJarvis, extend `learning.routing.router.HeuristicRouter`:

```python
from openjarvis.routing import HeuristicRouter
from lar1_classifier import classify

class LAR1Router(HeuristicRouter):
    def route(self, query, metadata=None):
        if metadata and metadata.get("LAR-1"):
            decision = classify(metadata["LAR-1"])
            return decision.route, decision.model_name
        return super().route(query)
```

## Configuration

`~/.openjarvis/config.toml`:

```toml
[skills.lar1-routing]
threshold_low = 0.3
threshold_medium = 0.5
threshold_high = 0.7
model_local_fast = "qwen2.5-7b"
model_cloud_premium = "gpt-4o"
```

## Files

```
skills/lar1-semantic-routing/
├── SKILL.md              — Agent instructions
├── skill.toml            — Pipeline definition
├── config.toml           — Tunable thresholds
├── scripts/
│   └── lar1_classifier.py  — Routing engine (8 rules)
└── examples/
    └── openjarvis_lar1_example.py — 6-scenario demo
```

## License

Apache 2.0
