"""EditApplier ABC, registry, and context types for the execute phase.

Each concrete applier implements validate/apply/rollback for a single EditOp.
Appliers are registered in an EditApplierRegistry keyed by EditOp.

See spec §7.1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from openjarvis.learning.spec_search.models import Edit, EditOp


@dataclass
class ApplyContext:
    """Shared context passed to all appliers."""

    openjarvis_home: Path
    session_id: str

    @property
    def config_path(self) -> Path:
        return self.openjarvis_home / "config.toml"

    @property
    def agents_dir(self) -> Path:
        return self.openjarvis_home / "agents"

    @property
    def tools_dir(self) -> Path:
        return self.openjarvis_home / "tools"


@dataclass
class ValidationResult:
    """Result of EditApplier.validate()."""

    ok: bool
    reason: str = ""


@dataclass
class ApplyResult:
    """Result of EditApplier.apply()."""

    changed_files: list[str] = field(default_factory=list)


class EditApplier(ABC):
    """Abstract base for edit appliers.

    Each subclass handles one EditOp. It validates the edit against
    the current config state, applies the mutation, and can roll back.
    """

    op: ClassVar[EditOp]

    @abstractmethod
    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        """Check if the edit can be applied to the current config."""
        ...

    @abstractmethod
    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        """Mutate the config. Must be idempotent."""
        ...

    @abstractmethod
    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        """Restore pre-edit state. Most appliers delegate to git checkout."""
        ...


class EditApplierRegistry:
    """Registry of EditApplier instances keyed by EditOp."""

    def __init__(self) -> None:
        self._appliers: dict[EditOp, EditApplier] = {}

    def register(self, applier: EditApplier) -> None:
        """Register an applier instance."""
        self._appliers[applier.op] = applier

    def get(self, op: EditOp) -> EditApplier:
        """Return the applier for the given op. Raises KeyError if not found."""
        return self._appliers[op]

    def is_supported(self, op: EditOp) -> bool:
        """Return True if an applier is registered for the op."""
        return op in self._appliers
