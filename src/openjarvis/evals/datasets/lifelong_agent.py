"""LifelongAgentBench: Sequential task learning benchmark.

Evaluates agents on sequential tasks across DB, OS, and KG environments
where knowledge from previous tasks is needed.
Source: arXiv:2505.11942
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an agent operating in a live environment. "
    "Complete the following task using the tools available to you. "
    "Previous tasks in this session may have modified the environment."
)

_KG_SYSTEM = (
    "You are a knowledge graph reasoning agent. Answer the question by "
    "analyzing the provided knowledge graph operations and entity information. "
    "Reason through each step and provide the final answer directly."
)


class LifelongAgentDataset(DatasetProvider):
    """LifelongAgentBench sequential task learning benchmark."""

    dataset_id = "lifelong-agent"
    dataset_name = "LifelongAgentBench"

    def __init__(
        self,
        subset: str = "database",
        cache_dir: Optional[str] = None,
    ) -> None:
        self._subset = subset  # "database", "os", "knowledge_graph"
        self._cache_dir = (
            Path(cache_dir) if cache_dir
            else Path.home() / ".cache" / "lifelong_agent"
        )
        self._records: List[EvalRecord] = []
        self._episodes: List[List[EvalRecord]] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        data_dir = self._cache_dir / self._subset

        if not data_dir.exists():
            self._download(data_dir)

        # Try Parquet first (HuggingFace format), then JSON/JSONL
        records = self._load_from_parquet(data_dir)
        if not records:
            task_sequences = self._load_task_sequences(data_dir)
            if seed is not None:
                random.Random(seed).shuffle(task_sequences)
            if max_samples is not None:
                task_sequences = task_sequences[:max_samples]
            self._episodes = []
            self._records = []
            for seq in task_sequences:
                episode = self._sequence_to_episode(seq)
                self._episodes.append(episode)
                self._records.extend(episode)
            return

        if seed is not None:
            random.Random(seed).shuffle(records)
        if max_samples is not None:
            records = records[:max_samples]
        self._records = records

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def iter_episodes(self) -> Iterable[List[EvalRecord]]:
        """Yield task sequences for episode mode."""
        return iter(self._episodes)

    def size(self) -> int:
        return len(self._records)

    def _download(self, data_dir: Path) -> None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise ImportError(
                "huggingface_hub required. Install with: pip install huggingface_hub"
            ) from exc
        data_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id="csyq/LifelongAgentBench",
            repo_type="dataset",
            local_dir=str(data_dir),
        )

    def _load_from_parquet(self, data_dir: Path) -> List[EvalRecord]:
        """Load records from Parquet files (HuggingFace dataset format)."""
        parquet_files = list(data_dir.rglob("*.parquet"))
        if not parquet_files:
            return []

        try:
            import pandas as pd
        except ImportError:
            logger.warning("pandas required for Parquet loading")
            return []

        records: List[EvalRecord] = []
        for pf in sorted(parquet_files):
            subset_name = pf.parent.name
            df = pd.read_parquet(pf)
            logger.info("Loading %d rows from %s", len(df), pf)

            for _, row in df.iterrows():
                row_dict = row.to_dict()
                if subset_name == "knowledge_graph":
                    rec = self._kg_row_to_record(row_dict)
                elif subset_name == "db_bench":
                    rec = self._db_row_to_record(row_dict)
                elif subset_name == "os_interaction":
                    rec = self._os_row_to_record(row_dict)
                else:
                    rec = self._generic_row_to_record(row_dict, subset_name)
                if rec is not None:
                    records.append(rec)

        return records

    def _kg_row_to_record(self, row: Dict[str, Any]) -> Optional[EvalRecord]:
        question = row.get("question", "")
        if not question:
            return None

        qid = row.get("qid", row.get("sample_index", "unknown"))
        entity_dict = row.get("entity_dict", {})
        if isinstance(entity_dict, str):
            try:
                entity_dict = json.loads(entity_dict)
            except (json.JSONDecodeError, TypeError):
                entity_dict = {}

        entity_desc = ""
        if isinstance(entity_dict, dict) and entity_dict:
            entities = "\n".join(
                f"  - {name}: {mid}" for name, mid in entity_dict.items()
            )
            entity_desc = f"Entities:\n{entities}"

        action_list = row.get("action_list", [])
        action_desc = ""
        if action_list:
            if isinstance(action_list, str):
                try:
                    action_list = json.loads(action_list)
                except (json.JSONDecodeError, TypeError):
                    action_list = []
            if isinstance(action_list, list) and action_list:
                steps = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(action_list))
                action_desc = f"\n\nKG Operations:\n{steps}"

        s_expr = row.get("s_expression", "")
        s_expr_desc = ""
        if s_expr:
            s_expr_desc = f"\n\nStructured Query:\n{s_expr}"

        problem = (
            f"{_KG_SYSTEM}\n\n"
            f"{entity_desc}"
            f"{action_desc}"
            f"{s_expr_desc}\n\n"
            f"Question: {question}"
        )

        answer_list = row.get("answer_list", [])
        if isinstance(answer_list, str):
            try:
                answer_list = json.loads(answer_list)
            except (json.JSONDecodeError, TypeError):
                answer_list = [answer_list]
        reference = ", ".join(str(a) for a in answer_list) if answer_list else ""

        return EvalRecord(
            record_id=f"lifelong-kg-{qid}",
            problem=problem,
            reference=reference,
            category="agentic",
            subject="knowledge_graph",
            metadata={
                "subset": "knowledge_graph",
                "qid": qid,
                "action_list": action_list,
                "skill_list": row.get("skill_list", []),
            },
        )

    def _db_row_to_record(self, row: Dict[str, Any]) -> Optional[EvalRecord]:
        instruction = row.get("instruction", "")
        if not instruction:
            return None

        idx = row.get("sample_index", "unknown")
        table_info = row.get("table_info", {})
        if isinstance(table_info, str):
            try:
                table_info = json.loads(table_info)
            except (json.JSONDecodeError, TypeError):
                table_info = {}

        table_ctx = ""
        if isinstance(table_info, dict) and table_info:
            tname = table_info.get("name", "unknown")
            cols = table_info.get("column_info_list", [])
            if cols:
                col_desc = ", ".join(
                    f"{c.get('name', '?')} ({c.get('type', '?')})" for c in cols
                )
                table_ctx = f"\n\nTable: {tname}\nColumns: {col_desc}"

        problem = f"{_SYSTEM_PROMPT}\n\n## Task\n{instruction}{table_ctx}"

        answer_info = row.get("answer_info", {})
        if isinstance(answer_info, str):
            try:
                answer_info = json.loads(answer_info)
            except (json.JSONDecodeError, TypeError):
                answer_info = {}

        reference = ""
        if isinstance(answer_info, dict):
            if answer_info.get("direct") is not None:
                reference = str(answer_info["direct"])
            elif answer_info.get("sql"):
                reference = answer_info["sql"]
            elif answer_info.get("md5"):
                reference = answer_info["md5"]

        return EvalRecord(
            record_id=f"lifelong-db-{idx}",
            problem=problem,
            reference=reference,
            category="agentic",
            subject="database",
            metadata={
                "subset": "db_bench",
                "sample_index": idx,
                "skill_list": row.get("skill_list", []),
            },
        )

    def _os_row_to_record(self, row: Dict[str, Any]) -> Optional[EvalRecord]:
        instruction = row.get("instruction", "")
        if not instruction:
            return None

        idx = row.get("sample_index", "unknown")
        problem = f"{_SYSTEM_PROMPT}\n\n## Task\n{instruction}"

        eval_info = row.get("evaluation_info", {})
        if isinstance(eval_info, str):
            try:
                eval_info = json.loads(eval_info)
            except (json.JSONDecodeError, TypeError):
                eval_info = {}

        reference = ""
        if isinstance(eval_info, dict):
            cmd_item = eval_info.get("evaluation_command_item", {})
            if isinstance(cmd_item, dict):
                reference = cmd_item.get("script", "")

        return EvalRecord(
            record_id=f"lifelong-os-{idx}",
            problem=problem,
            reference=reference,
            category="agentic",
            subject="os",
            metadata={
                "subset": "os_interaction",
                "sample_index": idx,
                "skill_list": row.get("skill_list", []),
            },
        )

    def _generic_row_to_record(
        self, row: Dict[str, Any], subset_name: str,
    ) -> Optional[EvalRecord]:
        instruction = row.get("instruction", row.get("question", row.get("task", "")))
        if not instruction:
            return None
        idx = row.get("sample_index", row.get("id", "unknown"))
        expected = row.get("answer", row.get("expected_output", ""))
        return EvalRecord(
            record_id=f"lifelong-{subset_name}-{idx}",
            problem=f"{_SYSTEM_PROMPT}\n\n## Task\n{instruction}",
            reference=str(expected),
            category="agentic",
            subject=subset_name,
            metadata={"subset": subset_name, "sample_index": idx},
        )

    def _load_task_sequences(
        self, data_dir: Path,
    ) -> List[List[Dict[str, Any]]]:
        """Load task sequences from JSON/JSONL files (legacy format)."""
        sequences: List[List[Dict[str, Any]]] = []

        for p in sorted(data_dir.rglob("*.json")):
            try:
                with open(p) as f:
                    data = json.load(f)
                if isinstance(data, list):
                    if data and isinstance(data[0], list):
                        sequences.extend(data)
                    elif data and isinstance(data[0], dict):
                        sequences.append(data)
                elif isinstance(data, dict):
                    tasks = data.get("tasks", data.get("sequence", [data]))
                    if tasks:
                        sequences.append(tasks if isinstance(tasks, list) else [tasks])
            except (json.JSONDecodeError, OSError):
                logger.debug("Skipping file: %s", p)

        for p in sorted(data_dir.rglob("*.jsonl")):
            try:
                seq: List[Dict[str, Any]] = []
                with open(p) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            seq.append(json.loads(line))
                if seq:
                    sequences.append(seq)
            except (json.JSONDecodeError, OSError):
                logger.debug("Skipping file: %s", p)

        return sequences

    def _sequence_to_episode(
        self, tasks: List[Dict[str, Any]],
    ) -> List[EvalRecord]:
        """Convert a task sequence into EvalRecords."""
        records: List[EvalRecord] = []
        seq_id = tasks[0].get("sequence_id", tasks[0].get("id", "unknown")) if tasks else "unknown"

        for i, task in enumerate(tasks):
            task_id = task.get("task_id", task.get("id", f"task-{i}"))
            instruction = task.get("instruction", task.get("task", ""))
            expected = task.get("expected_output", task.get("answer", ""))
            env_type = task.get("environment", self._subset)
            dependencies = task.get("dependencies", [])

            problem = (
                f"{_SYSTEM_PROMPT}\n\n"
                f"## Task {i + 1}\n{instruction}"
            )
            if dependencies:
                problem += f"\n\nThis task depends on previous tasks: {dependencies}"

            records.append(EvalRecord(
                record_id=f"lifelong-{seq_id}-t{i}",
                problem=problem,
                reference=expected,
                category="agentic",
                subject=env_type,
                metadata={
                    "sequence_id": seq_id,
                    "task_index": i,
                    "environment": env_type,
                    "dependencies": dependencies,
                    "task_id": task_id,
                },
            ))

        return records


__all__ = ["LifelongAgentDataset"]
