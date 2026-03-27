"""Recipe loader — load and resolve TOML recipe files.

Recipes are the universal composition format for OpenJarvis.  Each recipe
specifies all five primitives (Intelligence, Engine, Agent, Tools, Learning)
and carries a ``kind`` that determines its lifecycle:

* ``"discrete"`` — one-shot or benchmark-oriented agents
* ``"operator"`` — persistent, scheduled agents
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


# Built-in recipes directory (package data)
_PROJECT_RECIPES_DIR = Path(__file__).resolve().parent / "data"
_PROJECT_OPERATORS_DIR = _PROJECT_RECIPES_DIR / "operators"
# User-level directories
_USER_RECIPES_DIR = Path.home() / ".openjarvis" / "recipes"
_USER_OPERATORS_DIR = Path.home() / ".openjarvis" / "operators"


@dataclass(slots=True)
class Recipe:
    """A composable primitive configuration loaded from TOML.

    Covers both *discrete* agents (benchmarking / one-shot) and *operator*
    agents (persistent / scheduled) through the ``kind`` field.
    """

    name: str
    description: str = ""
    version: str = "0.1.0"
    kind: str = "discrete"  # "discrete" | "operator"

    # Intelligence
    model: Optional[str] = None
    quantization: Optional[str] = None
    provider: Optional[str] = None

    # Engine
    engine_key: Optional[str] = None

    # Agent
    agent_type: Optional[str] = None
    max_turns: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    tools: List[str] = field(default_factory=list)
    system_prompt: Optional[str] = None
    system_prompt_path: Optional[str] = None

    # Learning
    routing_policy: Optional[str] = None
    agent_policy: Optional[str] = None

    # Eval (discrete agents)
    eval_suites: List[str] = field(default_factory=list)
    eval_benchmarks: List[str] = field(default_factory=list)
    eval_backend: Optional[str] = None
    eval_max_samples: Optional[int] = None
    eval_judge_model: Optional[str] = None

    # Schedule (operators)
    schedule_type: Optional[str] = None
    schedule_value: Optional[str] = None

    # Channels (operators)
    channels: List[str] = field(default_factory=list)

    # Security
    required_capabilities: List[str] = field(default_factory=list)

    # Raw TOML data for forward-compat
    raw: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Conversion helpers
    # ------------------------------------------------------------------ #

    def to_builder_kwargs(self) -> Dict[str, Any]:
        """Convert recipe fields to kwargs for SystemBuilder/Jarvis.

        Returns a dict with only the non-None fields, keyed to match
        the SystemBuilder fluent API or Jarvis constructor parameters.
        """
        kwargs: Dict[str, Any] = {}
        if self.model is not None:
            kwargs["model"] = self.model
        if self.engine_key is not None:
            kwargs["engine_key"] = self.engine_key
        if self.agent_type is not None:
            kwargs["agent"] = self.agent_type
        if self.tools:
            kwargs["tools"] = self.tools
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.max_turns is not None:
            kwargs["max_turns"] = self.max_turns
        prompt = self.system_prompt
        if prompt is None and self.system_prompt_path is not None:
            p = Path(self.system_prompt_path)
            if p.exists():
                prompt = p.read_text(encoding="utf-8")
        if prompt is not None:
            kwargs["system_prompt"] = prompt
        if self.routing_policy is not None:
            kwargs["routing_policy"] = self.routing_policy
        if self.agent_policy is not None:
            kwargs["agent_policy"] = self.agent_policy
        if self.quantization is not None:
            kwargs["quantization"] = self.quantization
        if self.provider is not None:
            kwargs["provider"] = self.provider
        if self.eval_suites:
            kwargs["eval_suites"] = self.eval_suites
        return kwargs

    def to_eval_suite(
        self,
        benchmarks: Optional[List[str]] = None,
        max_samples: Optional[int] = None,
        judge_model: Optional[str] = None,
    ) -> Any:
        """Convert this recipe into an ``EvalSuiteConfig``.

        Uses the recipe's model/engine as the single ``[[models]]`` entry
        and the recipe's benchmarks (or *benchmarks* override) as
        ``[[benchmarks]]``, inheriting agent type and tools.
        """
        from openjarvis.recipes.composer import recipe_to_eval_suite

        return recipe_to_eval_suite(
            self,
            benchmarks=benchmarks,
            max_samples=max_samples,
            judge_model=judge_model,
        )

    def to_operator_manifest(self) -> Any:
        """Convert this recipe into an ``OperatorManifest``."""
        from openjarvis.recipes.composer import recipe_to_operator

        return recipe_to_operator(self)


# ------------------------------------------------------------------ #
# TOML loader
# ------------------------------------------------------------------ #


def load_recipe(path: str | Path) -> Recipe:
    """Load a recipe from a TOML file.

    Supports the unified format with ``[recipe]``, ``[intelligence]``,
    ``[engine]``, ``[agent]``, ``[learning]``, ``[eval]``, ``[schedule]``,
    and ``[channels]`` sections.  Also auto-detects legacy operator manifests
    that use ``[operator]`` as the top-level key.

    Raises:
        FileNotFoundError: If *path* does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Recipe file not found: {path}")

    with open(path, "rb") as fh:
        data = tomllib.load(fh)

    # Auto-detect legacy operator manifests ([operator] key)
    if "operator" in data and "recipe" not in data:
        return _load_operator_as_recipe(path, data)

    recipe_sec = data.get("recipe", {})
    intel_sec = data.get("intelligence", {})
    engine_sec = data.get("engine", {})
    agent_sec = data.get("agent", {})
    learning_sec = data.get("learning", {})
    eval_sec = data.get("eval", {})
    schedule_sec = data.get("schedule", {})
    channels_sec = data.get("channels", {})

    system_prompt = agent_sec.get("system_prompt")
    system_prompt_path = agent_sec.get("system_prompt_path")

    # Resolve external prompt relative to TOML file
    if not system_prompt and system_prompt_path:
        prompt_p = Path(system_prompt_path)
        if not prompt_p.is_absolute():
            prompt_p = path.parent / prompt_p
        if prompt_p.exists():
            system_prompt = prompt_p.read_text(encoding="utf-8")
            system_prompt_path = str(prompt_p)

    kind = recipe_sec.get("kind", "discrete")
    if schedule_sec and kind == "discrete":
        kind = "operator"

    return Recipe(
        name=recipe_sec.get("name", path.stem),
        description=recipe_sec.get("description", ""),
        version=recipe_sec.get("version", "0.1.0"),
        kind=kind,
        model=intel_sec.get("model"),
        quantization=intel_sec.get("quantization"),
        provider=intel_sec.get("provider") or engine_sec.get("provider"),
        engine_key=engine_sec.get("key"),
        agent_type=agent_sec.get("type"),
        max_turns=agent_sec.get("max_turns"),
        temperature=agent_sec.get("temperature"),
        tools=agent_sec.get("tools", []),
        system_prompt=system_prompt,
        system_prompt_path=system_prompt_path,
        routing_policy=learning_sec.get("routing"),
        agent_policy=learning_sec.get("agent"),
        eval_suites=eval_sec.get("suites", []),
        eval_benchmarks=eval_sec.get("benchmarks", []),
        eval_backend=eval_sec.get("backend"),
        eval_max_samples=eval_sec.get("max_samples"),
        eval_judge_model=eval_sec.get("judge_model"),
        schedule_type=schedule_sec.get("type"),
        schedule_value=str(schedule_sec["value"]) if "value" in schedule_sec else None,
        channels=channels_sec.get("output", []),
        required_capabilities=recipe_sec.get("required_capabilities", []),
        raw=data,
    )


def _load_operator_as_recipe(path: Path, data: Dict[str, Any]) -> Recipe:
    """Convert a legacy ``[operator]`` manifest into a Recipe."""
    op = data["operator"]
    agent_data = op.get("agent", {})
    schedule = op.get("schedule", {})

    system_prompt = agent_data.get("system_prompt", op.get("system_prompt", ""))
    system_prompt_path = agent_data.get(
        "system_prompt_path",
        op.get("system_prompt_path", ""),
    )
    if not system_prompt and system_prompt_path:
        prompt_p = Path(system_prompt_path)
        if not prompt_p.is_absolute():
            prompt_p = path.parent / prompt_p
        if prompt_p.exists():
            system_prompt = prompt_p.read_text(encoding="utf-8")
            system_prompt_path = str(prompt_p)

    sched_type = schedule.get("type", op.get("schedule_type", "interval"))
    sched_value = schedule.get("value", op.get("schedule_value", "300"))

    return Recipe(
        name=op.get("name", path.stem),
        description=op.get("description", ""),
        version=op.get("version", "0.1.0"),
        kind="operator",
        tools=agent_data.get("tools", op.get("tools", [])),
        system_prompt=system_prompt or None,
        system_prompt_path=system_prompt_path or None,
        max_turns=agent_data.get("max_turns", op.get("max_turns", 20)),
        temperature=agent_data.get("temperature", op.get("temperature", 0.3)),
        schedule_type=sched_type,
        schedule_value=str(sched_value),
        required_capabilities=op.get("required_capabilities", []),
        raw=data,
    )


# ------------------------------------------------------------------ #
# Discovery
# ------------------------------------------------------------------ #


def discover_recipes(
    extra_dirs: Optional[List[str | Path]] = None,
    *,
    kind: Optional[str] = None,
) -> List[Recipe]:
    """Discover all TOML recipes from known directories.

    Search order (later entries override earlier ones by name):
    1. Project ``recipes/data/`` directory (discrete recipes)
    2. Project ``recipes/data/operators/`` directory (operator recipes)
    3. User ``~/.openjarvis/recipes/`` directory
    4. User ``~/.openjarvis/operators/`` directory
    5. Any additional directories in *extra_dirs*

    Args:
        extra_dirs: Additional directories to scan.
        kind: If set, filter to only "discrete" or "operator" recipes.
    """
    dirs: List[Path] = [
        _PROJECT_RECIPES_DIR,
        _PROJECT_OPERATORS_DIR,
        _USER_RECIPES_DIR,
        _USER_OPERATORS_DIR,
    ]
    if extra_dirs:
        dirs.extend(Path(d) for d in extra_dirs)

    recipes: Dict[str, Recipe] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for toml_path in sorted(d.glob("*.toml")):
            try:
                recipe = load_recipe(toml_path)
                if kind is None or recipe.kind == kind:
                    recipes[recipe.name] = recipe
            except Exception:
                continue

    return list(recipes.values())


def resolve_recipe(name: str) -> Optional[Recipe]:
    """Find a recipe by name from all known directories.

    Returns ``None`` if no recipe with the given name is found.
    """
    for recipe in discover_recipes():
        if recipe.name == name:
            return recipe
    return None


__all__ = ["Recipe", "discover_recipes", "load_recipe", "resolve_recipe"]
