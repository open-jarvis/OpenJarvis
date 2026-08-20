"""DeepPlanning: long-horizon planning with constraints.

Evaluates agents on complex shopping tasks with hard constraints
(product attributes, ratings, stock, shipping).
Source: https://huggingface.co/datasets/Qwen/DeepPlanning
Paper: arXiv:2601.18137

The dataset contains shopping planning tasks at 3 difficulty levels
(120 total cases). Each case has a natural-language query, product
catalog, and ground-truth product selections with constraint metadata.
"""

from __future__ import annotations

import json
import logging
import random
import tarfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a shopping assistant. Given the user's request and a product catalog, "
    "select the correct products that satisfy ALL stated constraints.\n\n"
    "IMPORTANT INSTRUCTIONS:\n"
    "- Read through the product catalog data directly — do NOT write code to parse it\n"
    "- For each constraint, find products matching ALL requirements\n"
    "- If a constraint references data not in the catalog (e.g., transport time "
    "when only shipping provider is listed), use reasonable inference from "
    "available shipping info\n"
    "- For each selected product, state: name, brand, price, and the specific "
    "attribute values that match each constraint\n"
    "- Present your final answer as a clear list of selected products"
)


class DeepPlanningDataset(DatasetProvider):
    """DeepPlanning long-horizon planning benchmark.

    Extracts shopping planning tasks from Qwen/DeepPlanning tar.gz archives.
    Each case has a query with constraints and ground-truth product selections.
    """

    dataset_id = "deepplanning"
    dataset_name = "DeepPlanning"

    def __init__(
        self,
        cache_dir: Optional[str] = None,
    ) -> None:
        self._cache_dir = cache_dir
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        snapshot_dir = self._find_snapshot_dir()
        if snapshot_dir is None:
            self._download_dataset()
            snapshot_dir = self._find_snapshot_dir()
            if snapshot_dir is None:
                logger.error("Failed to download DeepPlanning dataset")
                return

        records: List[EvalRecord] = []
        for level in [1, 2, 3]:
            tar_path = snapshot_dir / f"database_level{level}.tar.gz"
            if not tar_path.exists():
                logger.warning("Missing %s", tar_path)
                continue
            level_records = self._extract_cases(tar_path, level)
            records.extend(level_records)

        logger.info("Loaded %d DeepPlanning cases", len(records))

        if seed is not None:
            random.Random(seed).shuffle(records)
        if max_samples is not None:
            records = records[:max_samples]

        self._records = records

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def _find_snapshot_dir(self) -> Optional[Path]:
        """Find the HF cache snapshot directory for Qwen/DeepPlanning."""
        base = Path.home() / ".cache" / "huggingface" / "hub"
        ds_dir = base / "datasets--Qwen--DeepPlanning" / "snapshots"
        if not ds_dir.exists():
            return None
        snapshots = list(ds_dir.iterdir())
        return snapshots[0] if snapshots else None

    def _download_dataset(self) -> None:
        """Trigger HF datasets download to populate the cache."""
        try:
            from datasets import load_dataset
        except ImportError:
            raise ImportError(
                "datasets required for DeepPlanning. Install with: pip install datasets"
            )
        logger.info("Downloading Qwen/DeepPlanning from HuggingFace...")
        # Loading triggers the download even though we don't use the result
        load_dataset("Qwen/DeepPlanning", split="train")

    def _extract_cases(
        self,
        tar_path: Path,
        level: int,
    ) -> List[EvalRecord]:
        """Extract shopping cases from a tar.gz archive."""
        records: List[EvalRecord] = []
        try:
            with tarfile.open(tar_path, "r:gz") as tf:
                # Build index of all members by directory
                members_by_dir: Dict[str, Dict[str, Any]] = {}
                for m in tf.getmembers():
                    parts = Path(m.name).parts
                    if len(parts) >= 2:
                        case_dir = parts[1]  # e.g. "case_12"
                        fname = parts[-1]
                        members_by_dir.setdefault(case_dir, {})[fname] = m

                for case_name, files in members_by_dir.items():
                    val_member = files.get("validation_cases.json")
                    prod_member = files.get("products.jsonl")
                    if val_member is None:
                        continue

                    f = tf.extractfile(val_member)
                    if f is None:
                        continue
                    data = json.loads(f.read().decode("utf-8"))

                    # Load product catalog
                    products_text = ""
                    if prod_member is not None:
                        pf = tf.extractfile(prod_member)
                        if pf is not None:
                            products_text = pf.read().decode("utf-8").strip()

                    rec = self._case_to_record(
                        data,
                        level,
                        case_name,
                        products_text,
                    )
                    if rec:
                        records.append(rec)
        except Exception:
            logger.warning("Failed to read %s", tar_path, exc_info=True)
        return records

    def _case_to_record(
        self,
        data: Dict[str, Any],
        level: int,
        case_name: str,
        products_text: str = "",
    ) -> Optional[EvalRecord]:
        """Convert a validation_cases.json to an EvalRecord."""
        query = data.get("query", "")
        if not query:
            return None

        ground_truth = data.get("ground_truth_products", [])
        meta_info = data.get("meta_info", [])

        # Build reference as structured summary
        ref_parts = []
        for prod in ground_truth:
            name = prod.get("name", "")
            brand = prod.get("brand", "")
            price = prod.get("price", "")
            ref_parts.append(f"{brand} {name} (${price})")
        reference = "; ".join(ref_parts) if ref_parts else ""

        # Count constraints
        n_constraints = sum(len(m.get("features", [])) for m in meta_info)

        difficulty = "easy" if level == 1 else "medium" if level == 2 else "hard"

        # Build product catalog section
        catalog_section = ""
        if products_text:
            catalog_section = (
                f"## Product Catalog\n"
                f"Below is the product database in JSONL format "
                f"(one JSON object per line):\n\n"
                f"```jsonl\n{products_text}\n```\n\n"
            )

        problem = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"## Shopping Request\n{query}\n\n"
            f"{catalog_section}"
            f"## Required Output\n"
            f"List each product that satisfies ALL constraints. For each product:\n"
            f"1. Product name and brand\n"
            f"2. Price\n"
            f"3. For each constraint, the matching attribute value from the catalog"
        )

        return EvalRecord(
            record_id=f"deepplanning-L{level}-{case_name}",
            problem=problem,
            reference=reference,
            category="agentic",
            subject=f"shopping_L{level}",
            metadata={
                "task_type": "shopping",
                "level": level,
                "difficulty": difficulty,
                "case_name": case_name,
                "n_products": len(ground_truth),
                "n_constraints": n_constraints,
                "ground_truth_products": ground_truth,
                "meta_info": meta_info,
            },
        )


__all__ = ["DeepPlanningDataset"]
