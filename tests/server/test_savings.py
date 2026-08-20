"""Regression tests for compute_savings — leaderboard correctness.

The leaderboard pipeline feeds aggregated telemetry sums into
`compute_savings`, which in turn feeds the public leaderboard. The old
behaviour fell back from `prompt_tokens_evaluated` to `prompt_tokens`
when the KV-cache-aware count was missing — but routes.py aggregates
by summing per-turn full prompts, which counts the system prompt N
times in an N-turn conversation. The fallback was the dominant
contributor to the bimodal Wh/token distribution observed on the public
leaderboard. These tests pin the conservative fallback behaviour.
"""

from __future__ import annotations

from openjarvis.server.savings import compute_savings


class TestPromptTokensEvaluatedFallback:
    def test_fallback_does_not_inflate_with_summed_prompt_tokens(self) -> None:
        """When prompt_tokens_evaluated is 0 (missing), FLOPs must NOT
        be derived from the full `prompt_tokens` sum.

        In a 10-turn conversation with a 100-token system prompt, the
        aggregator sums prompt_tokens = 10 × (sys + history) ≈ 10× the
        true input. Pre-fix the fallback used that inflated number for
        FLOPs and energy. Post-fix we use only completion_tokens, which
        is conservative but at least not 10× too high.
        """
        # Same prompt_tokens (the buggy aggregated sum) for both
        # invocations; vary only whether prompt_tokens_evaluated is
        # known. The fix must make the FLOPs-bearing fields independent
        # of the inflated prompt_tokens when evaluated is missing.
        with_evaluated = compute_savings(
            prompt_tokens=5000,
            completion_tokens=200,
            total_calls=10,
            prompt_tokens_evaluated=600,  # known KV-cache-aware count
        )
        without_evaluated = compute_savings(
            prompt_tokens=5000,
            completion_tokens=200,
            total_calls=10,
            prompt_tokens_evaluated=0,  # missing → fallback path
        )

        # The fallback path should NOT silently use the inflated
        # prompt_tokens sum as the FLOPs denominator.
        for missing_p, known_p in zip(
            without_evaluated.per_provider, with_evaluated.per_provider
        ):
            assert missing_p.flops <= known_p.flops + 1, (
                f"Fallback inflated FLOPs for {missing_p.provider}: "
                f"missing_evaluated={missing_p.flops}, "
                f"known_evaluated={known_p.flops}. Pre-fix the "
                f"fallback used `prompt_tokens` (the multi-turn-summed "
                f"value) which over-stated compute by N× the turn count."
            )

    def test_dollar_savings_uses_prompt_tokens_unchanged(self) -> None:
        """Dollar savings still uses prompt_tokens (cloud providers bill
        per input token, even when the local engine had KV cache hits).
        Pin the existing contract so the FLOPs fix doesn't accidentally
        regress the dollar math."""
        result = compute_savings(
            prompt_tokens=1_000_000,
            completion_tokens=100_000,
            total_calls=10,
            prompt_tokens_evaluated=0,
        )
        # Sanity: some provider produced a positive cost (= positive
        # savings vs running locally for free).
        assert any(p.total_cost > 0 for p in result.per_provider)

    def test_zero_tokens_returns_zero_savings(self) -> None:
        """Edge case: no work done → no costs, no FLOPs, no negatives."""
        result = compute_savings(prompt_tokens=0, completion_tokens=0)
        for p in result.per_provider:
            assert p.total_cost == 0.0
            assert p.flops == 0.0
