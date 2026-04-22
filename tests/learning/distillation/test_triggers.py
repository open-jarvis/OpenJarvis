"""Tests for openjarvis.learning.distillation.triggers module."""

from __future__ import annotations


class TestOnDemandTrigger:
    def test_constructs(self) -> None:
        from openjarvis.learning.distillation.triggers import OnDemandTrigger

        t = OnDemandTrigger()
        assert t.kind.value == "on_demand"
        assert t.metadata == {}

    def test_metadata(self) -> None:
        from openjarvis.learning.distillation.triggers import OnDemandTrigger

        t = OnDemandTrigger(metadata={"source": "cli"})
        assert t.metadata["source"] == "cli"


class TestUserFlagTrigger:
    def test_constructs_with_trace_id(self) -> None:
        from openjarvis.learning.distillation.triggers import UserFlagTrigger

        t = UserFlagTrigger(trace_id="trace-001")
        assert t.kind.value == "user_flag"
        assert t.trace_id == "trace-001"
        assert "trace_id" in t.metadata


class TestScheduledTrigger:
    def test_constructs(self) -> None:
        from openjarvis.learning.distillation.triggers import ScheduledTrigger

        t = ScheduledTrigger(cron="0 3 * * *", new_trace_count=25)
        assert t.kind.value == "scheduled"
        assert t.cron == "0 3 * * *"
        assert t.new_trace_count == 25


class TestClusterTrigger:
    def test_constructs(self) -> None:
        from openjarvis.learning.distillation.triggers import ClusterTrigger

        t = ClusterTrigger(
            cluster_description="math failures",
            trace_ids=["t1", "t2", "t3"],
            failure_rate=0.8,
        )
        assert t.kind.value == "cluster"
        assert len(t.trace_ids) == 3
        assert t.failure_rate == 0.8
