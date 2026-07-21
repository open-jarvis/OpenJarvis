# LAR-1 Semantic Routing Skill

## Description
Route agent queries to the cheapest capable model using LAR-1 semantic metadata (time, cognition, evidence, confidence). Reduces cloud API costs by 50%+ compared to all-cloud routing with no quality loss.

## Installation
```
jarvis skill install github:cloudiaspecula/OpenJarvis --skills-dir skills/lar1-semantic-routing
```

## Usage
```
jarvis ask "What is 2+2?" --metadata '{"LAR-1": {"T": "now", "C": "obs", "E": "direct", "L": 0.99}}'
```

## LAR-1 Semantic Dimensions

| Field | Values | Routing |
|-------|--------|---------|
| T (Time) | now, recall, future, perpetual | recall → cloud; else → local |
| C (Cognition) | obs, exp, dec, meta, unc | unc/exp → cloud; else → local |
| E (Evidence) | direct, speculative, derived:log | speculative → cloud |
| L (Likelihood) | 0.0–1.0 | <0.3 → cloud premium; 0.3–0.5 → cloud fast; >0.7 → local fast |
| S (Space) | chat, workspace, web | routing context |

## Files
- `scripts/lar1_classifier.py` — Python routing engine (8 priority-ordered rules)
- `examples/openjarvis_lar1_example.py` — 6-scenario demo
- `config.toml` — tunable thresholds

## License
Apache 2.0
