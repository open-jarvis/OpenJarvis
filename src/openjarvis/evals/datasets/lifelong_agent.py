"""LifelongAgentBench dataset loader.

Faithful reimplementation of:
  https://github.com/caixd-220529/LifelongAgentBench
  https://huggingface.co/datasets/csyq/LifelongAgentBench
  Paper: arXiv:2505.11942

The HF dataset has three subsets stored as separate parquet directories:
  - db_bench      (SQL tasks against MySQL database tables)
  - knowledge_graph (KG reasoning via multi-turn API actions)
  - os_interaction  (Bash tasks in a Docker Ubuntu container)

Key design decisions matching the original:

1. **Lifelong episodes**: Tasks within each subset are ordered by
   ``sample_index`` and yielded as a single episode via
   ``iter_episodes()``.  When the eval runner uses ``episode_mode=True``,
   tasks are processed sequentially, enabling lifelong learning
   (in-context example injection from prior successes, mirroring the
   original's ``PreviousSampleUtilizationCallback``).

2. **Multi-turn interaction**: Each record provides a ``create_task_env()``
   that returns a ``TaskEnvironment`` for multi-turn agent interaction.
   DB tasks interact with a real database, KG tasks with an API simulator,
   OS tasks with a Docker container — matching the original's protocol.

3. **Environment requirements**: DB tasks need Docker+MySQL (SQLite fallback
   warns loudly).  OS tasks need Docker.  KG tasks need a SPARQL endpoint
   for full fidelity (oracle simulation with clear warning otherwise).
"""

from __future__ import annotations

import ast
import json
import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)

_HF_REPO_ID = "csyq/LifelongAgentBench"

_VALID_SUBSETS = ("db_bench", "knowledge_graph", "os_interaction")

# ---------------------------------------------------------------------------
# System prompts matching the original's interaction protocol
# ---------------------------------------------------------------------------

_DB_SYSTEM_PROMPT = (
    "I will ask you a question, then you should help me operate a MySQL "
    "database with SQL to answer the question.\n"
    "You have to explain the problem and your solution to me and write "
    "down your thoughts.\n"
    "After thinking and explaining, every round, you are only allowed to "
    "operate with one SQL statement at a time.\n"
    "Every time you can only execute one SQL statement. I will execute "
    "the SQL statement on the MySQL database and return the result to you.\n\n"
    'If the question cannot be answered, respond with "N/A".\n\n'
    "To execute SQL, respond with:\n"
    "Action: Operation\n"
    "```sql\n<SQL statement>\n```\n\n"
    "When you have the final answer, respond with:\n"
    "Action: Answer\n"
    "Final Answer: <answer>"
)

_KG_SYSTEM_PROMPT = (
    "You are an agent that answers questions by interacting with a "
    "Knowledge Graph (KG).\n\n"
    "Available API calls:\n"
    "1. get_relations(variable: var) -> list of relations\n"
    "2. get_neighbors(variable: var, relation: str) -> variable\n"
    "3. intersection(variable: var, ...) -> variable\n"
    "4. get_attributes(variable: var, relation: str) -> list of attributes\n"
    "5. argmax(variable: var, relation: str) -> variable\n"
    "6. argmin(variable: var, relation: str) -> variable\n"
    "7. count(variable: var) -> int\n\n"
    "Variables are denoted as #0, #1, #2, etc. Each API call that returns "
    "a variable creates a new variable with the next available index.\n"
    "You can also use entity IDs directly (e.g. m.02h8b9t) as arguments.\n\n"
    "After reasoning through the knowledge graph, provide your final answer "
    "by referencing the variable that contains the result:\n"
    "Final Answer: #N\n"
    "where N is the variable index holding the answer."
)

_OS_SYSTEM_PROMPT = (
    "You are an assistant that helps users interact with an Ubuntu "
    "operating system via bash commands.\n\n"
    "To execute a command, respond with:\n"
    "Act: bash\n"
    "```bash\n<command>\n```\n\n"
    "When you have completed the task, respond with:\n"
    "Act: finish"
)


def _parse_field(raw: Any) -> Any:
    """Parse a field that may be a Python-repr string or already a dict/list."""
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        pass
    return raw


def _parse_skills(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(s) for s in raw]
    if isinstance(raw, str):
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return [str(s) for s in parsed]
        except (ValueError, SyntaxError):
            pass
    return []


class LifelongAgentDataset(DatasetProvider):
    """LifelongAgentBench dataset loader.

    Loads from HuggingFace with three subsets: db_bench, knowledge_graph,
    os_interaction.  Set ``subset="all"`` to load all subsets (default).

    Tasks within each subset form a *lifelong episode* — they are
    processed sequentially with the agent accumulating experience across
    tasks.  Use ``episode_mode=True`` in RunConfig to enable this,
    mirroring the original's ``PreviousSampleUtilizationCallback``.

    Provides ``create_task_env(record)`` for multi-turn interactive
    evaluation, matching the original's multi-turn agent-environment
    interaction protocol.
    """

    dataset_id = "lifelong-agent"
    dataset_name = "LifelongAgentBench"

    def __init__(
        self,
        subset: str = "all",
        cache_dir: Optional[str] = None,
        sparql_endpoint: Optional[str] = None,
        os_image: Optional[str] = None,
    ) -> None:
        if subset != "all" and subset not in _VALID_SUBSETS:
            raise ValueError(
                f"Unknown subset {subset!r}. "
                f"Choose from: {list(_VALID_SUBSETS)} or 'all'"
            )
        self._subset = subset
        self._cache_dir = cache_dir
        self._sparql_endpoint = sparql_endpoint
        self._os_image = os_image
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        subsets = list(_VALID_SUBSETS) if self._subset == "all" else [self._subset]
        self._records = []
        load_failures: List[str] = []

        for subset in subsets:
            rows = self._load_subset_from_hf(subset)
            if not rows:
                msg = (
                    f"LifelongAgentBench[{subset}]: loaded 0 rows. "
                    f"This means evaluation for this subset CANNOT proceed. "
                    f"Ensure 'datasets' is installed: pip install datasets"
                )
                logger.error(msg)
                load_failures.append(msg)
                continue

            # Sort by sample_index to preserve lifelong ordering
            rows.sort(key=lambda r: r.get("sample_index", 0))

            converter = {
                "db_bench": self._row_to_record_db,
                "knowledge_graph": self._row_to_record_kg,
                "os_interaction": self._row_to_record_os,
            }[subset]

            subset_count = 0
            for row in rows:
                record = converter(row)
                if record is not None:
                    self._records.append(record)
                    subset_count += 1

            logger.info(
                "LifelongAgentBench[%s]: loaded %d records",
                subset,
                subset_count,
            )

        # Fail loudly if nothing loaded
        if not self._records:
            raise RuntimeError(
                "LifelongAgentBench: loaded 0 records across all subsets. "
                "The benchmark cannot run. Failures:\n" + "\n".join(load_failures)
            )

        # NOTE: Do NOT shuffle records.  The original LifelongAgentBench
        # processes tasks strictly by sample_index within each subset —
        # shuffling would break the lifelong learning protocol where later
        # tasks may depend on skills/state from earlier ones.  The seed
        # parameter is accepted for API compatibility but ignored.
        if seed is not None:
            logger.info(
                "LifelongAgentBench: seed=%d ignored — lifelong protocol "
                "requires strict sample_index ordering.",
                seed,
            )

        if max_samples is not None:
            self._records = self._records[:max_samples]

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def iter_episodes(self) -> Iterable[List[EvalRecord]]:
        """Yield one lifelong episode per subset, ordered by sample_index.

        The original benchmark processes all tasks within a subset
        sequentially, accumulating successful completions as in-context
        examples for subsequent tasks.  This method groups records by
        subset and sorts by ``sample_index`` so the eval runner can
        replicate this lifelong protocol when ``episode_mode=True``.
        """
        by_subset: Dict[str, List[EvalRecord]] = defaultdict(list)
        for record in self._records:
            by_subset[record.metadata["subset"]].append(record)

        for subset in sorted(by_subset):
            episode = sorted(
                by_subset[subset],
                key=lambda r: r.metadata["sample_index"],
            )
            for i, record in enumerate(episode):
                record.metadata["episode_task_index"] = i
                record.metadata["episode_length"] = len(episode)
            yield episode

    def create_task_env(self, record: EvalRecord):
        """Create a multi-turn TaskEnvironment for interactive evaluation.

        This is called by EvalRunner when episode_mode=True and enables
        the faithful multi-turn interaction protocol matching the original.
        """
        from openjarvis.evals.environments.lifelong_agent_env import (
            create_task_environment,
        )

        return create_task_environment(
            record,
            sparql_endpoint=self._sparql_endpoint,
            os_image=self._os_image,
        )

    def size(self) -> int:
        return len(self._records)

    def verify_requirements(self) -> List[str]:
        missing = []
        try:
            import datasets  # noqa: F401
        except ImportError:
            missing.append("The 'datasets' library is required: pip install datasets")
        return missing

    # ------------------------------------------------------------------
    # HuggingFace loading
    # ------------------------------------------------------------------

    def _load_subset_from_hf(self, subset: str) -> List[Dict[str, Any]]:
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise ImportError(
                "The 'datasets' library is required for LifelongAgentBench. "
                "Install with: pip install datasets"
            ) from exc

        # Try loading with data_files (the HF dataset stores subsets as
        # separate parquet directories without formal configs)
        kwargs: Dict[str, Any] = {
            "data_files": f"{subset}/*.parquet",
            "split": "train",
        }
        if self._cache_dir:
            kwargs["cache_dir"] = self._cache_dir

        try:
            ds = load_dataset(_HF_REPO_ID, **kwargs)
        except Exception:
            # Fallback: try loading as a named config
            try:
                ds = load_dataset(
                    _HF_REPO_ID,
                    name=subset,
                    split="train",
                    cache_dir=self._cache_dir,
                )
            except Exception as exc2:
                logger.error(
                    "FAILED to load %s[%s] from HuggingFace: %s\n"
                    "Tried both data_files='%s/*.parquet' and name='%s'.\n"
                    "Check your network connection and 'datasets' installation.",
                    _HF_REPO_ID,
                    subset,
                    exc2,
                    subset,
                    subset,
                )
                return []

        rows = [dict(row) for row in ds]
        if not rows:
            logger.error(
                "LifelongAgentBench[%s]: HF dataset loaded but contains 0 rows. "
                "This likely indicates a dataset structure mismatch.",
                subset,
            )
        return rows

    # ------------------------------------------------------------------
    # db_bench records
    # ------------------------------------------------------------------

    def _row_to_record_db(self, row: Dict[str, Any]) -> Optional[EvalRecord]:
        """Convert a db_bench row.

        Schema: sample_index, instruction, table_info, answer_info, skill_list
        """
        idx = row.get("sample_index", 0)
        instruction = row.get("instruction", "")
        if not instruction:
            logger.debug("Skipping db row %s: empty instruction", idx)
            return None

        table_info = _parse_field(row.get("table_info", "{}"))
        answer_info = _parse_field(row.get("answer_info", "{}"))
        skills = _parse_skills(row.get("skill_list", "[]"))

        if not isinstance(table_info, dict):
            logger.warning("Skipping db row %s: table_info is not a dict", idx)
            return None
        if not isinstance(answer_info, dict):
            logger.warning("Skipping db row %s: answer_info is not a dict", idx)
            return None

        table_name = table_info.get("name", "data")
        columns = table_info.get("column_info_list", [])
        sample_rows = table_info.get("row_list", [])

        # Build schema text matching original's initial chat history
        schema_lines = [f"Table: {table_name}", "Columns:"]
        for col in columns:
            cname = col.get("name", "?")
            ctype = col.get("type", "?")
            schema_lines.append(f"  - {cname} ({ctype})")
        if sample_rows:
            col_names = [c.get("name", "?") for c in columns]
            schema_lines.append(f"\nSample data ({len(sample_rows)} rows):")
            schema_lines.append(f"  {col_names}")
            for r in sample_rows[:5]:
                schema_lines.append(f"  {r}")
            if len(sample_rows) > 5:
                schema_lines.append(f"  ... ({len(sample_rows) - 5} more rows)")

        has_md5 = bool(
            answer_info.get("md5")
            and str(answer_info["md5"]) not in ("null", "None", "")
        )
        answer_type = "md5" if has_md5 else "direct"

        problem = (
            f"{_DB_SYSTEM_PROMPT}\n\n"
            f"## Database Schema\n{chr(10).join(schema_lines)}\n\n"
            f"## Task\n{instruction}"
        )

        return EvalRecord(
            record_id=f"lifelong-db-{idx}",
            problem=problem,
            reference=json.dumps(answer_info, default=str),
            category="agentic",
            subject=f"db_{answer_type}",
            metadata={
                "sample_index": idx,
                "subset": "db_bench",
                "table_info": table_info,
                "answer_info": answer_info,
                "answer_type": answer_type,
                "skills": skills,
                "table_name": table_name,
                "ground_truth_sql": answer_info.get("sql", ""),
            },
        )

    # ------------------------------------------------------------------
    # knowledge_graph records
    # ------------------------------------------------------------------

    def _row_to_record_kg(self, row: Dict[str, Any]) -> Optional[EvalRecord]:
        """Convert a knowledge_graph row.

        Schema: sample_index, question, qid, source, entity_dict,
                s_expression, action_list, answer_list, skill_list
        """
        idx = row.get("sample_index", 0)
        question = row.get("question", "")
        if not question:
            logger.debug("Skipping kg row %s: empty question", idx)
            return None

        entity_dict = _parse_field(row.get("entity_dict", "{}"))
        action_list = _parse_field(row.get("action_list", "[]"))
        answer_list = _parse_field(row.get("answer_list", "[]"))
        skills = _parse_skills(row.get("skill_list", "[]"))
        s_expression = row.get("s_expression", "")

        entity_lines = []
        if isinstance(entity_dict, dict):
            for name, mid in entity_dict.items():
                entity_lines.append(f"  - {name}: {mid}")

        problem = f"{_KG_SYSTEM_PROMPT}\n\n"
        if entity_lines:
            problem += f"## Known Entities\n{chr(10).join(entity_lines)}\n\n"
        problem += f"## Question\n{question}"

        ref_answers = answer_list if isinstance(answer_list, list) else [answer_list]

        return EvalRecord(
            record_id=f"lifelong-kg-{idx}",
            problem=problem,
            reference=json.dumps(ref_answers, default=str),
            category="agentic",
            subject="knowledge_graph",
            metadata={
                "sample_index": idx,
                "subset": "knowledge_graph",
                "question": question,
                "qid": row.get("qid", ""),
                "source": row.get("source", ""),
                "entity_dict": entity_dict if isinstance(entity_dict, dict) else {},
                "s_expression": s_expression,
                "action_list": action_list if isinstance(action_list, list) else [],
                "answer_list": ref_answers,
                "skills": skills,
            },
        )

    # ------------------------------------------------------------------
    # os_interaction records
    # ------------------------------------------------------------------

    def _row_to_record_os(self, row: Dict[str, Any]) -> Optional[EvalRecord]:
        """Convert an os_interaction row.

        Schema: sample_index, instruction, initialization_command_item,
                evaluation_info, skill_list
        """
        idx = row.get("sample_index", 0)
        instruction = row.get("instruction", "")
        if not instruction:
            logger.debug("Skipping os row %s: empty instruction", idx)
            return None

        init_cmd = _parse_field(row.get("initialization_command_item", "{}"))
        eval_info = _parse_field(row.get("evaluation_info", "{}"))
        skills = _parse_skills(row.get("skill_list", "[]"))

        eval_cmd = {}
        if isinstance(eval_info, dict):
            eval_cmd = eval_info.get("evaluation_command_item", eval_info)

        problem = f"{_OS_SYSTEM_PROMPT}\n\n## Task\n{instruction}"

        return EvalRecord(
            record_id=f"lifelong-os-{idx}",
            problem=problem,
            reference=json.dumps(eval_cmd, default=str),
            category="agentic",
            subject="os_interaction",
            metadata={
                "sample_index": idx,
                "subset": "os_interaction",
                "instruction": instruction,
                "init_command": init_cmd if isinstance(init_cmd, dict) else {},
                "evaluation_info": eval_info if isinstance(eval_info, dict) else {},
                "evaluation_command": eval_cmd,
                "skills": skills,
            },
        )


__all__ = ["LifelongAgentDataset"]
