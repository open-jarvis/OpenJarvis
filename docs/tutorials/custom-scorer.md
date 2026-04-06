# Creating Custom Eval Scorers

This tutorial guides you through creating a custom scorer for evaluating agent responses in OpenJarvis.

## Overview

Scorers are classes that evaluate agent outputs against expected behavior. They are used in the eval framework to measure performance across different dimensions.

## Basic Scorer Structure

A scorer is any callable that accepts an `EvalInput` and returns an `EvalOutput`:

```python
from openjarvis.evals.core.types import EvalInput, EvalOutput

def my_scorer(input: EvalInput) -> EvalOutput:
    """Evaluate agent response quality."""
    score = 0.0
    reasoning = ""
    
    # Your scoring logic here
    if "expected" in input.response.lower():
        score = 1.0
        reasoning = "Response contains expected keyword"
    else:
        reasoning = "Response missing expected keyword"
    
    return EvalOutput(
        score=score,
        reasoning=reasoning,
        metadata={"scorer": "keyword_match"}
    )
```

## Scorer Types

### 1. Exact Match Scorer

```python
from openjarvis.evals.core.types import EvalInput, EvalOutput

class ExactMatchScorer:
    """Scorer that checks for exact expected output."""
    
    def __init__(self, expected_key: str):
        self.expected_key = expected_key
    
    def __call__(self, input: EvalInput) -> EvalOutput:
        expected = input.extra.get(self.expected_key)
        actual = input.response
        
        if expected is None:
            return EvalOutput(
                score=0.0,
                reasoning="No expected value provided",
                metadata={"error": "missing_expected"}
            )
        
        is_match = expected.strip() == actual.strip()
        
        return EvalOutput(
            score=1.0 if is_match else 0.0,
            reasoning=f"{'Match' if is_match else 'No match'}: expected '{expected}', got '{actual[:50]}...'",
            metadata={"match": is_match, "expected": expected, "actual": actual[:100]}
        )
```

### 2. LLM-as-Judge Scorer

```python
from openjarvis.evals.core.types import EvalInput, EvalOutput

class LLMJudgeScorer:
    """Use an LLM to judge response quality."""
    
    def __init__(self, engine, prompt_template: str):
        self.engine = engine
        self.template = prompt_template
    
    def __call__(self, input: EvalInput) -> EvalOutput:
        prompt = self.template.format(
            question=input.query,
            response=input.response,
            reference=input.extra.get("reference", "")
        )
        
        result = self.engine.generate([
            {"role": "user", "content": prompt}
        ])
        
        # Parse score from LLM response
        score = self._parse_score(result.content)
        
        return EvalOutput(
            score=score,
            reasoning=result.content[:500],
            metadata={"judge_model": self.engine.model}
        )
    
    def _parse_score(self, response: str) -> float:
        """Extract numeric score from LLM response."""
        import re
        match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*10", response)
        if match:
            return float(match.group(1)) / 10
        return 0.5  # default
```

### 3. Multi-Dimensional Scorer

```python
from openjarvis.evals.core.types import EvalInput, EvalOutput
from dataclasses import dataclass
from typing import List

@dataclass
class DimensionScore:
    name: str
    score: float
    reasoning: str

class MultiDimensionalScorer:
    """Score multiple aspects of the response."""
    
    def __init__(self, dimensions: List[str]):
        self.dimensions = dimensions
    
    def __call__(self, input: EvalInput) -> EvalOutput:
        scores = []
        
        if "accuracy" in self.dimensions:
            scores.append(self._score_accuracy(input))
        
        if "helpfulness" in self.dimensions:
            scores.append(self._score_helpfulness(input))
        
        if "conciseness" in self.dimensions:
            scores.append(self._score_conciseness(input))
        
        # Aggregate scores
        total = sum(s.score for s in scores) / len(scores)
        reasoning = " | ".join(s.reasoning for s in scores)
        
        return EvalOutput(
            score=total,
            reasoning=reasoning,
            metadata={"dimensions": {s.name: s.score for s in scores}}
        )
    
    def _score_accuracy(self, input: EvalInput) -> DimensionScore:
        """Score factual accuracy."""
        # Your logic here
        return DimensionScore("accuracy", 0.8, "Mostly accurate")
    
    def _score_helpfulness(self, input: EvalInput) -> DimensionScore:
        """Score helpfulness."""
        return DimensionScore("helpfulness", 0.9, "Very helpful")
    
    def _score_conciseness(self, input: EvalInput) -> DimensionScore:
        """Score conciseness."""
        word_count = len(input.response.split())
        score = 1.0 if word_count < 200 else max(0.0, 1.0 - (word_count - 200) / 800)
        return DimensionScore("conciseness", score, f"Word count: {word_count}")
```

## Registering Your Scorer

Add your scorer to the eval framework by creating a file in `evals/scorers/`:

```python
# src/openjarvis/evals/scorers/my_custom_scorer.py
from openjarvis.evals.core.types import EvalInput, EvalOutput
from openjarvis.core.registry import ScorerRegistry

@ScorerRegistry.register("my_custom")
def my_custom_scorer(input: EvalInput) -> EvalOutput:
    """My custom scorer description."""
    # Implementation
    pass
```

## Using Your Scorer in Eval Runs

```bash
# Command line
jarvis eval run --scorer my_custom --dataset my_dataset

# Or in Python
from openjarvis.evals.core.runner import EvalRunner

runner = EvalRunner(
    dataset="my_dataset",
    scorers=["my_custom", "exact_match"],
    backend="jarvis_direct"
)
results = runner.run()
```

## Best Practices

1. **Provide reasoning** - Always include clear reasoning in `EvalOutput`
2. **Handle edge cases** - Return sensible defaults for missing data
3. **Use metadata** - Store additional debugging info in metadata
4. **Test thoroughly** - Test with various input types before deploying
5. **Consider multiple runs** - For non-deterministic scorers, average over runs
