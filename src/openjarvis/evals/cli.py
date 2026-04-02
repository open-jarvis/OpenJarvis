"""CLI for the OpenJarvis evaluation framework."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from openjarvis.evals.core.display import (
    print_banner,
    print_completion,
    print_full_results,
    print_run_header,
    print_section,
    print_subject_table,
    print_suite_summary,
)

LOGGER = logging.getLogger(__name__)

# Registry of available benchmarks and their metadata
BENCHMARKS = {
    "supergpqa": {"category": "reasoning", "description": "SuperGPQA multiple-choice"},
    "gpqa": {"category": "reasoning", "description": "GPQA graduate-level MCQ"},
    "mmlu-pro": {"category": "reasoning", "description": "MMLU-Pro multiple-choice"},
    "math500": {"category": "reasoning", "description": "MATH-500 math problems"},
    "natural-reasoning": {"category": "reasoning", "description": "Natural Reasoning"},
    "hle": {"category": "reasoning", "description": "HLE hard challenges"},
    "simpleqa": {"category": "chat", "description": "SimpleQA factual QA"},
    "wildchat": {"category": "chat", "description": "WildChat conversation quality"},
    "ipw": {"category": "chat", "description": "IPW mixed benchmark"},
    "gaia": {"category": "agentic", "description": "GAIA agentic benchmark"},
    "frames": {"category": "rag", "description": "FRAMES multi-hop RAG"},
    "swebench": {"category": "agentic", "description": "SWE-bench code patches"},
    "swefficiency": {"category": "agentic", "description": "SWEfficiency optimization"},
    "terminalbench": {
        "category": "agentic",
        "description": "TerminalBench terminal tasks",
    },
    "terminalbench-native": {
        "category": "agentic",
        "description": "TerminalBench Native (Docker)",
    },
    "email_triage": {
        "category": "use-case",
        "description": "Email triage classification + draft",
    },
    "morning_brief": {
        "category": "use-case",
        "description": "Morning briefing generation",
    },
    "research_mining": {
        "category": "use-case",
        "description": "Research synthesis + accuracy",
    },
    "knowledge_base": {
        "category": "use-case",
        "description": "Document-grounded retrieval QA",
    },
    "coding_task": {
        "category": "use-case",
        "description": "Function-level code generation",
    },
    "loghub": {
        "category": "agentic",
        "description": "LogHub log anomaly detection",
    },
    "ama-bench": {
        "category": "agentic",
        "description": "AMA-Bench agent memory assessment",
    },
    "lifelong-agent": {
        "category": "agentic",
        "description": "LifelongAgentBench sequential task learning",
    },
    "deepplanning": {
        "category": "agentic",
        "description": "DeepPlanning shopping constraints",
    },
    "paperarena": {
        "category": "agentic",
        "description": "PaperArena paper analysis",
    },
    "webchorearena": {
        "category": "agentic",
        "description": "WebChoreArena web chore tasks",
    },
    "workarena": {
        "category": "agentic",
        "description": "WorkArena++ enterprise workflows",
    },
    "coding_assistant": {
        "category": "use-case",
        "description": "Bug-fix coding assistant (test-based)",
    },
    "security_scanner": {
        "category": "use-case",
        "description": "Security vulnerability scanner",
    },
    "daily_digest": {
        "category": "use-case",
        "description": "Daily briefing generation",
    },
    "doc_qa": {
        "category": "use-case",
        "description": "Document-grounded QA with citations",
    },
    "browser_assistant": {
        "category": "use-case",
        "description": "Web research with fact verification",
    },
    "pinchbench": {
        "category": "agentic",
        "description": "PinchBench real-world agent tasks",
    },
    "taubench": {
        "category": "agentic",
        "description": "TauBench multi-turn customer service",
    },
    "livecodebench": {
        "category": "coding",
        "description": "LiveCodeBench competitive programming",
    },
    "liveresearch": {
        "category": "agentic",
        "description": "LiveResearchBench deep research tasks",
    },
    "toolcall15": {
        "category": "agentic",
        "description": "ToolCall-15 tool calling benchmark",
    },
}

BACKENDS = {
    "jarvis-direct": "Engine-level inference (local or cloud)",
    "jarvis-agent": "Agent-level inference with tool calling",
}


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_backend(
    backend_name: str,
    engine_key: Optional[str],
    agent_name: str,
    tools: list[str],
    telemetry: bool = False,
    gpu_metrics: bool = False,
    model: Optional[str] = None,
):
    """Construct the appropriate backend."""
    if backend_name == "jarvis-agent":
        from openjarvis.evals.backends.jarvis_agent import JarvisAgentBackend

        return JarvisAgentBackend(
            engine_key=engine_key,
            agent_name=agent_name,
            tools=tools,
            telemetry=telemetry,
            gpu_metrics=gpu_metrics,
            model=model,
        )
    else:
        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        return JarvisDirectBackend(
            engine_key=engine_key,
            telemetry=telemetry,
            gpu_metrics=gpu_metrics,
        )


def _build_dataset(benchmark: str, subset: str | None = None):
    """Construct the dataset provider for a benchmark."""
    if benchmark == "supergpqa":
        from openjarvis.evals.datasets.supergpqa import SuperGPQADataset

        return SuperGPQADataset()
    elif benchmark == "gpqa":
        from openjarvis.evals.datasets.gpqa import GPQADataset

        return GPQADataset()
    elif benchmark == "mmlu-pro":
        from openjarvis.evals.datasets.mmlu_pro import MMLUProDataset

        return MMLUProDataset()
    elif benchmark == "math500":
        from openjarvis.evals.datasets.math500 import MATH500Dataset

        return MATH500Dataset()
    elif benchmark == "natural-reasoning":
        from openjarvis.evals.datasets.natural_reasoning import NaturalReasoningDataset

        return NaturalReasoningDataset()
    elif benchmark == "hle":
        from openjarvis.evals.datasets.hle import HLEDataset

        return HLEDataset()
    elif benchmark == "simpleqa":
        from openjarvis.evals.datasets.simpleqa import SimpleQADataset

        return SimpleQADataset()
    elif benchmark == "wildchat":
        from openjarvis.evals.datasets.wildchat import WildChatDataset

        return WildChatDataset()
    elif benchmark == "ipw":
        from openjarvis.evals.datasets.ipw_mixed import IPWDataset

        return IPWDataset()
    elif benchmark == "gaia":
        from openjarvis.evals.datasets.gaia import GAIADataset

        return GAIADataset()
    elif benchmark == "frames":
        from openjarvis.evals.datasets.frames import FRAMESDataset

        return FRAMESDataset()
    elif benchmark == "swebench":
        from openjarvis.evals.datasets.swebench import SWEBenchDataset

        return SWEBenchDataset()
    elif benchmark == "swefficiency":
        from openjarvis.evals.datasets.swefficiency import SWEfficiencyDataset

        return SWEfficiencyDataset()
    elif benchmark == "terminalbench":
        from openjarvis.evals.datasets.terminalbench import TerminalBenchDataset

        return TerminalBenchDataset()
    elif benchmark == "terminalbench-native":
        from openjarvis.evals.datasets.terminalbench_native import (
            TerminalBenchNativeDataset,
        )

        return TerminalBenchNativeDataset()
    elif benchmark == "email_triage":
        from openjarvis.evals.datasets.email_triage import EmailTriageDataset

        return EmailTriageDataset()
    elif benchmark == "morning_brief":
        from openjarvis.evals.datasets.morning_brief import MorningBriefDataset

        return MorningBriefDataset()
    elif benchmark == "research_mining":
        from openjarvis.evals.datasets.research_mining import ResearchMiningDataset

        return ResearchMiningDataset()
    elif benchmark == "knowledge_base":
        from openjarvis.evals.datasets.knowledge_base import KnowledgeBaseDataset

        return KnowledgeBaseDataset()
    elif benchmark == "coding_task":
        from openjarvis.evals.datasets.coding_task import CodingTaskDataset

        return CodingTaskDataset()
    elif benchmark == "loghub":
        from openjarvis.evals.datasets.loghub import LogHubDataset

        return LogHubDataset()
    elif benchmark == "ama-bench":
        from openjarvis.evals.datasets.ama_bench import AMABenchDataset

        return AMABenchDataset()
    elif benchmark == "lifelong-agent":
        from openjarvis.evals.datasets.lifelong_agent import LifelongAgentDataset

        return LifelongAgentDataset(subset=subset or "db_bench")
    elif benchmark == "deepplanning":
        from openjarvis.evals.datasets.deepplanning import DeepPlanningDataset

        return DeepPlanningDataset()
    elif benchmark == "paperarena":
        from openjarvis.evals.datasets.paperarena import PaperArenaDataset

        return PaperArenaDataset()
    elif benchmark == "webchorearena":
        from openjarvis.evals.datasets.webchorearena import WebChoreArenaDataset

        return WebChoreArenaDataset()
    elif benchmark == "workarena":
        from openjarvis.evals.datasets.workarena import WorkArenaDataset

        return WorkArenaDataset()
    elif benchmark == "coding_assistant":
        from openjarvis.evals.datasets.coding_assistant import CodingAssistantDataset

        return CodingAssistantDataset()
    elif benchmark == "security_scanner":
        from openjarvis.evals.datasets.security_scanner import SecurityScannerDataset

        return SecurityScannerDataset()
    elif benchmark == "daily_digest":
        from openjarvis.evals.datasets.daily_digest import DailyDigestDataset

        return DailyDigestDataset()
    elif benchmark == "doc_qa":
        from openjarvis.evals.datasets.doc_qa import DocQADataset

        return DocQADataset()
    elif benchmark == "browser_assistant":
        from openjarvis.evals.datasets.browser_assistant import BrowserAssistantDataset

        return BrowserAssistantDataset()
    elif benchmark == "pinchbench":
        from openjarvis.evals.datasets.pinchbench import PinchBenchDataset

        return PinchBenchDataset(path=subset)
    elif benchmark == "taubench":
        from openjarvis.evals.datasets.taubench import TauBenchDataset
        domains = subset.split(",") if subset else None
        return TauBenchDataset(domains=domains)
    elif benchmark == "livecodebench":
        from openjarvis.evals.datasets.livecodebench import LiveCodeBenchDataset

        return LiveCodeBenchDataset()
    elif benchmark == "liveresearch":
        from openjarvis.evals.datasets.liveresearch import LiveResearchBenchDataset

        return LiveResearchBenchDataset(path=subset)
    elif benchmark == "toolcall15":
        from openjarvis.evals.datasets.toolcall15 import ToolCall15Dataset

        return ToolCall15Dataset()
    else:
        raise click.ClickException(f"Unknown benchmark: {benchmark}")


def _build_scorer(benchmark: str, judge_backend, judge_model: str):
    """Construct the scorer for a benchmark."""
    if benchmark == "supergpqa":
        from openjarvis.evals.scorers.supergpqa_mcq import SuperGPQAScorer

        return SuperGPQAScorer(judge_backend, judge_model)
    elif benchmark == "gpqa":
        from openjarvis.evals.scorers.gpqa_mcq import GPQAScorer

        return GPQAScorer(judge_backend, judge_model)
    elif benchmark == "mmlu-pro":
        from openjarvis.evals.scorers.mmlu_pro_mcq import MMLUProScorer

        return MMLUProScorer(judge_backend, judge_model)
    elif benchmark == "math500" or benchmark == "natural-reasoning":
        from openjarvis.evals.scorers.reasoning_judge import ReasoningJudgeScorer

        return ReasoningJudgeScorer(judge_backend, judge_model)
    elif benchmark == "hle":
        from openjarvis.evals.scorers.hle_judge import HLEScorer

        return HLEScorer(judge_backend, judge_model)
    elif benchmark == "simpleqa":
        from openjarvis.evals.scorers.simpleqa_judge import SimpleQAScorer

        return SimpleQAScorer(judge_backend, judge_model)
    elif benchmark == "wildchat":
        from openjarvis.evals.scorers.wildchat_judge import WildChatScorer

        return WildChatScorer(judge_backend, judge_model)
    elif benchmark == "ipw":
        from openjarvis.evals.scorers.ipw_mixed import IPWMixedScorer

        return IPWMixedScorer(judge_backend, judge_model)
    elif benchmark == "gaia":
        from openjarvis.evals.scorers.gaia_exact import GAIAScorer

        return GAIAScorer(judge_backend, judge_model)
    elif benchmark == "frames":
        from openjarvis.evals.scorers.frames_judge import FRAMESScorer

        return FRAMESScorer(judge_backend, judge_model)
    elif benchmark == "swebench":
        from openjarvis.evals.scorers.swebench_structural import SWEBenchScorer

        return SWEBenchScorer(judge_backend, judge_model)
    elif benchmark == "swefficiency":
        from openjarvis.evals.scorers.swefficiency_structural import SWEfficiencyScorer

        return SWEfficiencyScorer(judge_backend, judge_model)
    elif benchmark == "terminalbench":
        from openjarvis.evals.scorers.terminalbench_judge import TerminalBenchScorer

        return TerminalBenchScorer(judge_backend, judge_model)
    elif benchmark == "terminalbench-native":
        from openjarvis.evals.scorers.terminalbench_native_structural import (
            TerminalBenchNativeScorer,
        )

        return TerminalBenchNativeScorer(judge_backend, judge_model)
    elif benchmark == "email_triage":
        from openjarvis.evals.scorers.email_triage import EmailTriageScorer

        return EmailTriageScorer(judge_backend, judge_model)
    elif benchmark == "morning_brief":
        from openjarvis.evals.scorers.morning_brief import MorningBriefScorer

        return MorningBriefScorer(judge_backend, judge_model)
    elif benchmark == "research_mining":
        from openjarvis.evals.scorers.research_mining import ResearchMiningScorer

        return ResearchMiningScorer(judge_backend, judge_model)
    elif benchmark == "knowledge_base":
        from openjarvis.evals.scorers.knowledge_base import KnowledgeBaseScorer

        return KnowledgeBaseScorer(judge_backend, judge_model)
    elif benchmark == "coding_task":
        from openjarvis.evals.scorers.coding_task import CodingTaskScorer

        return CodingTaskScorer(judge_backend, judge_model)
    elif benchmark == "loghub":
        from openjarvis.evals.scorers.loghub_scorer import LogHubScorer

        return LogHubScorer(judge_backend, judge_model)
    elif benchmark == "ama-bench":
        from openjarvis.evals.scorers.ama_bench_judge import AMABenchScorer

        return AMABenchScorer(judge_backend, judge_model)
    elif benchmark == "lifelong-agent":
        from openjarvis.evals.scorers.lifelong_agent_scorer import LifelongAgentScorer

        return LifelongAgentScorer(judge_backend, judge_model)
    elif benchmark == "deepplanning":
        from openjarvis.evals.scorers.deepplanning_scorer import DeepPlanningScorer

        return DeepPlanningScorer(judge_backend, judge_model)
    elif benchmark == "paperarena":
        from openjarvis.evals.scorers.paperarena_judge import PaperArenaScorer

        return PaperArenaScorer(judge_backend, judge_model)
    elif benchmark == "webchorearena":
        from openjarvis.evals.scorers.webchorearena_scorer import WebChoreArenaScorer

        return WebChoreArenaScorer(judge_backend, judge_model)
    elif benchmark == "workarena":
        from openjarvis.evals.scorers.workarena_scorer import WorkArenaScorer

        return WorkArenaScorer(judge_backend, judge_model)
    elif benchmark == "coding_assistant":
        from openjarvis.evals.scorers.coding_assistant import CodingAssistantScorer

        return CodingAssistantScorer(judge_backend, judge_model)
    elif benchmark == "security_scanner":
        from openjarvis.evals.scorers.security_scanner import SecurityScannerScorer

        return SecurityScannerScorer(judge_backend, judge_model)
    elif benchmark == "daily_digest":
        from openjarvis.evals.scorers.daily_digest import DailyDigestScorer

        return DailyDigestScorer(judge_backend, judge_model)
    elif benchmark == "doc_qa":
        from openjarvis.evals.scorers.doc_qa import DocQAScorer

        return DocQAScorer(judge_backend, judge_model)
    elif benchmark == "browser_assistant":
        from openjarvis.evals.scorers.browser_assistant import BrowserAssistantScorer

        return BrowserAssistantScorer(judge_backend, judge_model)
    elif benchmark == "pinchbench":
        from openjarvis.evals.scorers.pinchbench import PinchBenchScorer

        return PinchBenchScorer(judge_backend, judge_model)
    elif benchmark == "taubench":
        from openjarvis.evals.scorers.taubench import TauBenchScorer
        return TauBenchScorer(judge_backend, judge_model)
    elif benchmark == "livecodebench":
        from openjarvis.evals.scorers.livecodebench import LiveCodeBenchScorer

        return LiveCodeBenchScorer(judge_backend, judge_model)
    elif benchmark == "liveresearch":
        from openjarvis.evals.scorers.liveresearch import LiveResearchBenchScorer

        return LiveResearchBenchScorer(judge_backend, judge_model)
    elif benchmark == "toolcall15":
        from openjarvis.evals.scorers.toolcall15 import ToolCall15Scorer

        return ToolCall15Scorer(judge_backend, judge_model)
    else:
        raise click.ClickException(f"Unknown benchmark: {benchmark}")


def _build_judge_backend(judge_model: str, engine_key: str = "cloud"):
    """Build the judge backend for LLM-as-judge scoring.

    Returns None if no engine is reachable — deterministic scorers
    (e.g. LifelongAgentScorer, GAIAScorer) accept None and ignore it.
    LLM-judge scorers will raise a clear error when they actually try
    to use the backend rather than failing at startup.
    """
    from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

    try:
        return JarvisDirectBackend(engine_key=engine_key)
    except RuntimeError as exc:
        LOGGER.warning(
            "Judge backend (%s) unavailable: %s — "
            "deterministic scorers will still work; "
            "LLM-judge scorers will fail when scoring.",
            engine_key,
            exc,
        )
        return None


def _print_summary(
    summary,
    console: Optional[Console] = None,
    output_path: Optional[Path] = None,
    traces_dir: Optional[Path] = None,
    *,
    compact: bool = False,
    trace_detail: bool = False,
) -> None:
    """Print a single run summary using Rich display primitives."""
    if console is None:
        console = Console()
    print_section(console, "Results")
    print_full_results(console, summary, compact=compact, trace_detail=trace_detail)
    if not compact and summary.per_subject and len(summary.per_subject) > 1:
        print_subject_table(console, summary.per_subject)
    print_completion(console, summary, output_path, traces_dir)


def _build_trackers(config) -> list:
    """Build tracker instances from RunConfig fields."""
    trackers = []
    if getattr(config, "wandb_project", ""):
        try:
            from openjarvis.evals.trackers.wandb_tracker import WandbTracker

            trackers.append(
                WandbTracker(
                    project=config.wandb_project,
                    entity=getattr(config, "wandb_entity", ""),
                    tags=getattr(config, "wandb_tags", ""),
                    group=getattr(config, "wandb_group", ""),
                )
            )
        except ImportError as exc:
            raise click.ClickException(
                f"wandb not installed: {exc}\nInstall with: uv sync --extra eval-wandb"
            ) from exc
    if getattr(config, "sheets_spreadsheet_id", ""):
        try:
            from openjarvis.evals.trackers.sheets_tracker import SheetsTracker

            trackers.append(
                SheetsTracker(
                    spreadsheet_id=config.sheets_spreadsheet_id,
                    worksheet=getattr(config, "sheets_worksheet", "Results"),
                    credentials_path=getattr(config, "sheets_credentials_path", ""),
                )
            )
        except ImportError as exc:
            raise click.ClickException(
                f"gspread not installed: {exc}\n"
                "Install with: uv sync --extra eval-sheets"
            ) from exc
    return trackers


def _run_single(config, console: Optional[Console] = None) -> object:
    """Run a single eval from a RunConfig and return the summary."""
    from openjarvis.evals.core.runner import EvalRunner

    if console is None:
        console = Console()

    eval_backend = _build_backend(
        config.backend,
        config.engine_key,
        config.agent_name or "orchestrator",
        config.tools,
        telemetry=getattr(config, "telemetry", False),
        gpu_metrics=getattr(config, "gpu_metrics", False),
        model=config.model,
    )
    dataset = _build_dataset(config.benchmark)
    # Inject engine config for benchmarks that run their own simulation
    if hasattr(dataset, "set_engine_config"):
        dataset.set_engine_config(
            engine_key=config.engine_key,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            telemetry=getattr(config, "telemetry", False),
            gpu_metrics=getattr(config, "gpu_metrics", False),
        )
    judge_engine = getattr(config, "judge_engine", "cloud") or "cloud"
    judge_backend = _build_judge_backend(config.judge_model, engine_key=judge_engine)
    scorer = _build_scorer(config.benchmark, judge_backend, config.judge_model)

    trackers = _build_trackers(config)
    runner = EvalRunner(config, dataset, eval_backend, scorer, trackers=trackers)
    try:
        num_samples = config.max_samples or 0
        # Use progress bar if we know the sample count
        if num_samples > 0:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Evaluating samples...", total=num_samples)
                summary = runner.run(
                    progress_callback=lambda done, total: progress.update(
                        task,
                        completed=done,
                    ),
                )
        else:
            with console.status("Evaluating samples..."):
                summary = runner.run()
        return summary
    finally:
        eval_backend.close()
        if judge_backend is not None:
            judge_backend.close()


def _run_agentic(
    config,
    console: Optional[Console] = None,
    *,
    concurrency: int = 1,
    query_timeout: Optional[float] = None,
) -> None:
    """Run an agentic evaluation using AgenticRunner with trace + energy capture."""
    import asyncio
    from pathlib import Path as _Path

    from openjarvis.evals.core.agentic_runner import AgenticRunner
    from openjarvis.evals.core.event_recorder import EventRecorder
    from openjarvis.evals.core.export import (
        export_artifacts_manifest,
        export_jsonl,
        export_summary_json,
    )

    if console is None:
        console = Console()

    # Build dataset
    dataset = _build_dataset(config.benchmark, getattr(config, "dataset_subset", None))
    dataset.load(
        max_samples=config.max_samples,
        split=config.dataset_split,
        seed=config.seed,
    )

    # Wire judge for PinchBench LLM-judge and hybrid grading
    if config.benchmark == "pinchbench" and hasattr(dataset, "set_judge"):
        judge_engine = getattr(config, "judge_engine", "cloud") or "cloud"
        judge_model = (
            getattr(config, "judge_model", None) or "anthropic/claude-opus-4-5"
        )
        judge_backend = _build_judge_backend(judge_model, engine_key=judge_engine)
        dataset.set_judge(judge_backend, judge_model)

    # Verify backend requirements before doing any work
    if hasattr(dataset, "verify_requirements"):
        issues = dataset.verify_requirements()
        if issues:
            console.print(
                "\n[bold red]Cannot start evaluation — requirements not met:[/bold red]"
            )
            for issue in issues:
                console.print(f"[red]  • {issue}[/red]")
            raise click.ClickException(
                f"{config.benchmark} requirements not satisfied. "
                "Fix the issues above and retry."
            )

    # Build agent via SystemBuilder
    from openjarvis.system import SystemBuilder

    builder = SystemBuilder()
    if config.engine_key:
        builder.engine(config.engine_key)
    builder.model(config.model)
    agent_name = config.agent_name or "orchestrator"
    builder.agent(agent_name)
    tool_list = config.tools or []
    if tool_list:
        builder.tools(tool_list)
    system = builder.telemetry(config.telemetry).traces(config.telemetry).build()

    # Build TelemetrySession (optional — only if energy monitoring available)
    telemetry_session = None
    try:
        from openjarvis.telemetry.energy_monitor import create_energy_monitor
        from openjarvis.telemetry.session import TelemetrySession

        monitor = create_energy_monitor()
        if monitor is not None:
            telemetry_session = TelemetrySession(
                monitor=monitor,
                interval_ms=100,
            )
    except ImportError:
        pass

    # Set up run directory
    model_slug = config.model.replace("/", "-").replace(":", "-")
    if config.output_path:
        run_dir = _Path(config.output_path).parent
    else:
        run_dir = _Path("results")
    run_dir = run_dir / f"agentic_{config.benchmark}_{model_slug}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Build runner
    event_recorder = EventRecorder()
    runner = AgenticRunner(
        agent=system,
        dataset=dataset,
        telemetry_session=telemetry_session,
        config={
            "model": config.model,
            "benchmark": config.benchmark,
            "agent": agent_name,
            "tools": tool_list,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        },
        event_recorder=event_recorder,
        run_dir=run_dir,
        concurrency=concurrency,
        query_timeout=query_timeout,
    )

    # Execute with telemetry session context
    try:
        ctx = telemetry_session if telemetry_session is not None else _nullctx()
        with ctx:
            with console.status("Running agentic evaluation..."):
                traces = asyncio.run(runner.run(max_queries=config.max_samples))
    finally:
        system.close()
        if telemetry_session is not None and hasattr(telemetry_session, "stop"):
            try:
                telemetry_session.stop()
            except Exception:
                pass

    # Export results
    jsonl_path = run_dir / "traces.jsonl"
    export_jsonl(traces, jsonl_path)
    console.print(f"  [green]Traces:[/green]    {jsonl_path}")

    summary_path = run_dir / "summary.json"
    export_summary_json(
        traces,
        config={
            "model": config.model,
            "benchmark": config.benchmark,
            "agent": agent_name,
            "concurrency": concurrency,
            "query_timeout": query_timeout,
        },
        path=summary_path,
    )
    console.print(f"  [green]Summary:[/green]   {summary_path}")

    manifest = export_artifacts_manifest(run_dir)
    if manifest:
        console.print(f"  [green]Manifest:[/green]  {manifest}")

    # Try HF dataset export (optional)
    try:
        from openjarvis.evals.core.export import export_hf_dataset

        hf_path = run_dir / "hf_dataset"
        export_hf_dataset(traces, hf_path)
        console.print(f"  [green]HF Arrow:[/green]  {hf_path}")
    except ImportError:
        pass

    # Print summary table
    print_section(console, "Agentic Results")
    _print_agentic_summary(console, traces, config)


def _nullctx():
    """Return a no-op context manager."""
    from contextlib import nullcontext

    return nullcontext()


def _print_agentic_summary(console: Console, traces, config) -> None:
    """Print a rich summary of agentic run results."""
    from rich.table import Table

    completed = sum(1 for t in traces if t.completed)
    resolved = sum(1 for t in traces if t.is_resolved is True)
    timed_out = sum(1 for t in traces if t.timed_out)
    total_turns = sum(t.num_turns for t in traces)
    total_tool_calls = sum(t.total_tool_calls for t in traces)
    total_in_tok = sum(t.total_input_tokens for t in traces)
    total_out_tok = sum(t.total_output_tokens for t in traces)
    total_wall = sum(t.total_wall_clock_s for t in traces)

    gpu_energies = [
        t.total_gpu_energy_joules
        for t in traces
        if t.total_gpu_energy_joules is not None
    ]
    total_gpu_energy = sum(gpu_energies) if gpu_energies else None

    costs = [t.total_cost_usd for t in traces if t.total_cost_usd is not None]
    total_cost = sum(costs) if costs else None

    table = Table(
        title=f"[bold]{config.benchmark} / {config.model}[/bold]",
        border_style="bright_blue",
    )
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Queries", str(len(traces)))
    table.add_row("Completed", f"{completed}/{len(traces)}")
    if any(t.is_resolved is not None for t in traces):
        table.add_row("Resolved", f"{resolved}/{len(traces)}")
    table.add_row("Timed out", str(timed_out))
    table.add_row("Total turns", str(total_turns))
    avg_t = f"{total_turns / len(traces):.1f}" if traces else "0"
    table.add_row("Avg turns/query", avg_t)
    table.add_row("Total tool calls", str(total_tool_calls))
    table.add_row("Input tokens", f"{total_in_tok:,}")
    table.add_row("Output tokens", f"{total_out_tok:,}")
    table.add_row("Wall clock", f"{total_wall:.1f}s")
    table.add_row(
        "Avg query time",
        f"{total_wall / len(traces):.1f}s" if traces else "0s",
    )

    if total_gpu_energy is not None:
        table.add_row("GPU energy", f"{total_gpu_energy:.2f} J")
    if total_cost is not None:
        table.add_row("Total cost", f"${total_cost:.4f}")

    # Throughput
    if total_out_tok > 0 and total_wall > 0:
        table.add_row(
            "Throughput",
            f"{total_out_tok / total_wall:.1f} tok/s",
        )

    console.print(table)


def _run_from_config(
    config_path: str,
    verbose: bool,
    *,
    model_filter: str | None = None,
) -> None:
    """Load a TOML config and run the full models x benchmarks matrix."""
    from openjarvis.evals.core.config import expand_suite, load_eval_config

    console = Console()

    suite = load_eval_config(config_path)
    run_configs = expand_suite(suite)

    # Filter by model name substring if requested
    if model_filter:
        run_configs = [rc for rc in run_configs if model_filter in rc.model]
        if not run_configs:
            raise click.ClickException(f"No models match filter '{model_filter}'")

    suite_name = suite.meta.name or Path(config_path).stem

    # Banner + configuration
    print_banner(console)
    print_section(console, "Suite Configuration")
    console.print(f"  [cyan]Suite:[/cyan]       {suite_name}")
    if suite.meta.description:
        console.print(f"  [cyan]Description:[/cyan] {suite.meta.description}")
    console.print(
        f"  [cyan]Matrix:[/cyan]     {len(suite.models)} model(s) x "
        f"{len(suite.benchmarks)} benchmark(s) = {len(run_configs)} run(s)"
    )

    # Ensure output directory exists
    output_dir = Path(suite.run.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Auto-set wandb_group to suite name if W&B enabled and no explicit group
    for rc in run_configs:
        if rc.wandb_project and not rc.wandb_group:
            rc.wandb_group = suite_name

    summaries = []
    for i, rc in enumerate(run_configs, 1):
        print_section(
            console,
            f"Run {i}/{len(run_configs)}: {rc.benchmark} / {rc.model}",
        )
        try:
            summary = _run_single(rc, console=console)
            summaries.append(summary)
            console.print(
                f"  [green]{summary.accuracy:.4f}[/green] "
                f"({summary.correct}/{summary.scored_samples})"
            )
        except Exception as exc:
            console.print(f"  [red bold]FAILED:[/red bold] {exc}")

    # Print overall summary table
    if summaries:
        print_section(console, "Suite Results")
        print_suite_summary(console, summaries, suite_name)


@click.group()
def main():
    """OpenJarvis Evaluation Framework."""


@main.command()
@click.option(
    "-c",
    "--config",
    "config_path",
    default=None,
    type=click.Path(),
    help="TOML config file for suite runs",
)
@click.option(
    "-b",
    "--benchmark",
    default=None,
    type=click.Choice(list(BENCHMARKS.keys())),
    help="Benchmark to run",
)
@click.option(
    "--backend",
    default="jarvis-direct",
    type=click.Choice(list(BACKENDS.keys())),
    help="Inference backend",
)
@click.option("-m", "--model", default=None, help="Model identifier")
@click.option(
    "-e",
    "--engine",
    "engine_key",
    default=None,
    help="Engine key (ollama, vllm, cloud, ...)",
)
@click.option(
    "--agent",
    "agent_name",
    default="orchestrator",
    help="Agent name for jarvis-agent backend",
)
@click.option("--tools", default="", help="Comma-separated tool names")
@click.option(
    "-n", "--max-samples", type=int, default=None, help="Maximum samples to evaluate"
)
@click.option("-w", "--max-workers", type=int, default=4, help="Parallel workers")
@click.option("--judge-model", default="gpt-5-mini-2025-08-07", help="LLM judge model")
@click.option("-o", "--output", "output_path", default=None, help="Output JSONL path")
@click.option("--seed", type=int, default=42, help="Random seed")
@click.option("--split", "dataset_split", default=None, help="Dataset split override")
@click.option("--temperature", type=float, default=0.0, help="Generation temperature")
@click.option("--max-tokens", type=int, default=2048, help="Max output tokens")
@click.option(
    "--telemetry/--no-telemetry",
    default=False,
    help="Enable telemetry collection during eval",
)
@click.option(
    "--gpu-metrics/--no-gpu-metrics",
    default=False,
    help="Enable GPU metrics collection",
)
@click.option(
    "--compact",
    is_flag=True,
    default=False,
    help="Dense single-table output",
)
@click.option(
    "--trace-detail",
    is_flag=True,
    default=False,
    help="Full per-step trace listing",
)
@click.option("--wandb-project", default="", help="W&B project name (enables tracking)")
@click.option("--wandb-entity", default="", help="W&B entity (team or user)")
@click.option("--wandb-tags", default="", help="Comma-separated W&B tags")
@click.option("--wandb-group", default="", help="W&B run group")
@click.option(
    "--sheets-id",
    "sheets_spreadsheet_id",
    default="",
    help="Google Sheets spreadsheet ID",
)
@click.option(
    "--sheets-worksheet", default="Results", help="Google Sheets worksheet name"
)
@click.option(
    "--sheets-creds",
    "sheets_credentials_path",
    default="",
    help="Service account JSON path",
)
@click.option(
    "--model-filter",
    default=None,
    help="Filter models by name substring (for multi-model configs)",
)
@click.option(
    "--judge-engine",
    default="cloud",
    help="Engine key for LLM judge (default: cloud). Use 'vllm' to judge locally.",
)
@click.option(
    "--agentic",
    is_flag=True,
    default=False,
    help="Use AgenticRunner for multi-turn agent execution",
)
@click.option(
    "--episode-mode",
    is_flag=True,
    default=False,
    help="Sequential episode processing with lifelong learning "
    "(required for lifelong-agent and similar benchmarks)",
)
@click.option(
    "--concurrency",
    type=int,
    default=1,
    help="Parallel query execution (AgenticRunner only)",
)
@click.option(
    "--query-timeout",
    type=float,
    default=None,
    help="Per-query wall-clock timeout in seconds (AgenticRunner only)",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
@click.pass_context
def run(
    ctx,
    config_path,
    benchmark,
    backend,
    model,
    engine_key,
    agent_name,
    tools,
    max_samples,
    max_workers,
    judge_model,
    output_path,
    seed,
    dataset_split,
    temperature,
    max_tokens,
    telemetry,
    gpu_metrics,
    compact,
    trace_detail,
    wandb_project,
    wandb_entity,
    wandb_tags,
    wandb_group,
    sheets_spreadsheet_id,
    sheets_worksheet,
    sheets_credentials_path,
    model_filter,
    judge_engine,
    agentic,
    episode_mode,
    concurrency,
    query_timeout,
    verbose,
):
    """Run a single benchmark evaluation, or a full suite from a TOML config."""
    _setup_logging(verbose)

    console = Console()

    # Config-driven mode
    if config_path is not None:
        _run_from_config(config_path, verbose, model_filter=model_filter)
        return

    # CLI-driven mode: validate required args
    if benchmark is None:
        raise click.UsageError(
            "Missing option '-b' / '--benchmark' "
            "(required when --config is not provided)"
        )
    if model is None:
        raise click.UsageError(
            "Missing option '-m' / '--model' (required when --config is not provided)"
        )

    from openjarvis.evals.core.types import RunConfig

    tool_list = [t.strip() for t in tools.split(",") if t.strip()] if tools else []

    # --episode-mode takes precedence over --agentic.
    # Note: EvalRunner also auto-detects episode_mode from the dataset
    # (via iter_episodes), so passing --episode-mode here is optional for
    # benchmarks like lifelong-agent that always require it.
    if episode_mode and agentic:
        LOGGER.warning(
            "--episode-mode and --agentic both set; using --episode-mode "
            "(provides proper multi-turn interaction via EvalRunner)"
        )
        agentic = False

    config = RunConfig(
        benchmark=benchmark,
        backend=backend,
        model=model,
        max_samples=max_samples,
        max_workers=max_workers,
        temperature=temperature,
        max_tokens=max_tokens,
        judge_model=judge_model,
        judge_engine=judge_engine,
        engine_key=engine_key,
        agent_name=agent_name,
        tools=tool_list,
        output_path=output_path,
        seed=seed,
        dataset_split=dataset_split,
        telemetry=telemetry,
        gpu_metrics=gpu_metrics,
        wandb_project=wandb_project,
        wandb_entity=wandb_entity,
        wandb_tags=wandb_tags,
        wandb_group=wandb_group,
        sheets_spreadsheet_id=sheets_spreadsheet_id,
        sheets_worksheet=sheets_worksheet,
        sheets_credentials_path=sheets_credentials_path,
        episode_mode=episode_mode,
    )

    # Banner + config
    print_banner(console)
    print_section(console, "Configuration")
    print_run_header(
        console,
        benchmark=benchmark,
        model=model,
        backend=backend,
        samples=max_samples,
        workers=max_workers,
    )
    if episode_mode:
        console.print(
            "  [cyan]Mode:[/cyan]       episode (sequential + lifelong learning)"
        )

    if agentic:
        # --- Agentic runner path ---
        print_section(console, "Agentic Evaluation")
        console.print(f"  [cyan]Concurrency:[/cyan] {concurrency}")
        if query_timeout:
            console.print(f"  [cyan]Timeout:[/cyan]     {query_timeout}s per query")
        _run_agentic(
            config,
            console=console,
            concurrency=concurrency,
            query_timeout=query_timeout,
        )
        return

    # Evaluation
    print_section(console, "Evaluation")
    summary = _run_single(config, console=console)

    # Results
    _output_path = getattr(summary, "_output_path", None)
    _traces_dir = getattr(summary, "_traces_dir", None)
    _print_summary(
        summary,
        console=console,
        output_path=_output_path,
        traces_dir=_traces_dir,
        compact=compact,
        trace_detail=trace_detail,
    )


@main.command("run-all")
@click.option("-m", "--model", required=True, help="Model identifier")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine key")
@click.option(
    "-n", "--max-samples", type=int, default=None, help="Max samples per benchmark"
)
@click.option("-w", "--max-workers", type=int, default=4, help="Parallel workers")
@click.option("--judge-model", default="gpt-5-mini-2025-08-07", help="LLM judge model")
@click.option("--output-dir", default="results/", help="Output directory for results")
@click.option("--seed", type=int, default=42, help="Random seed")
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def run_all(
    model, engine_key, max_samples, max_workers, judge_model, output_dir, seed, verbose
):
    """Run all benchmarks."""
    _setup_logging(verbose)

    from openjarvis.evals.core.runner import EvalRunner
    from openjarvis.evals.core.types import RunConfig

    console = Console()

    print_banner(console)
    print_section(console, "Suite Configuration")
    console.print(
        f"  [cyan]Model:[/cyan]      {model}\n"
        f"  [cyan]Benchmarks:[/cyan] {', '.join(BENCHMARKS.keys())}\n"
        f"  [cyan]Samples:[/cyan]    {max_samples if max_samples else 'all'}"
    )

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    model_slug = model.replace("/", "-").replace(":", "-")
    summaries = []

    for i, bench_name in enumerate(BENCHMARKS, 1):
        print_section(console, f"Run {i}/{len(BENCHMARKS)}: {bench_name}")
        output_path = output_dir_path / f"{bench_name}_{model_slug}.jsonl"

        config = RunConfig(
            benchmark=bench_name,
            backend="jarvis-direct",
            model=model,
            max_samples=max_samples,
            max_workers=max_workers,
            judge_model=judge_model,
            engine_key=engine_key,
            output_path=str(output_path),
            seed=seed,
        )

        eval_backend = _build_backend("jarvis-direct", engine_key, "orchestrator", [])
        dataset = _build_dataset(bench_name)
        judge_backend = _build_judge_backend(judge_model, engine_key="cloud")
        scorer = _build_scorer(bench_name, judge_backend, judge_model)

        trackers = _build_trackers(config)
        runner = EvalRunner(config, dataset, eval_backend, scorer, trackers=trackers)
        try:
            if max_samples and max_samples > 0:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TimeRemainingColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task(
                        f"Evaluating {bench_name}...",
                        total=max_samples,
                    )
                    summary = runner.run(
                        progress_callback=lambda done, total: progress.update(
                            task,
                            completed=done,
                        ),
                    )
            else:
                with console.status(f"Evaluating {bench_name}..."):
                    summary = runner.run()
            summaries.append(summary)
            console.print(
                f"  [green]{summary.accuracy:.4f}[/green] "
                f"({summary.correct}/{summary.scored_samples})"
            )
        except Exception as exc:
            console.print(f"  [red bold]FAILED:[/red bold] {exc}")
        finally:
            eval_backend.close()
            if judge_backend is not None:
                judge_backend.close()

    # Print overall summary
    if summaries:
        print_section(console, "Suite Results")
        print_suite_summary(console, summaries, f"All Benchmarks / {model}")


@main.command()
@click.argument("jsonl_path", type=click.Path(exists=True))
def summarize(jsonl_path):
    """Summarize results from a JSONL output file."""
    records = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        click.echo("No records found.")
        return

    console = Console()
    total = len(records)
    scored = [r for r in records if r.get("is_correct") is not None]
    correct = [r for r in scored if r["is_correct"]]
    errors = [r for r in records if r.get("error")]
    accuracy = len(correct) / len(scored) if scored else 0.0

    console.print(f"[cyan]File:[/cyan]      {jsonl_path}")
    console.print(f"[cyan]Benchmark:[/cyan] {records[0].get('benchmark', '?')}")
    console.print(f"[cyan]Model:[/cyan]     {records[0].get('model', '?')}")
    console.print(f"[cyan]Total:[/cyan]     {total}")
    console.print(f"[cyan]Scored:[/cyan]    {len(scored)}")
    console.print(f"[cyan]Correct:[/cyan]   {len(correct)}")
    console.print(f"[cyan]Accuracy:[/cyan]  [bold]{accuracy:.4f}[/bold]")
    console.print(f"[cyan]Errors:[/cyan]    {len(errors)}")


@main.command("list")
def list_cmd():
    """List available benchmarks and backends."""
    console = Console()
    print_banner(console)

    from rich.table import Table

    bench_table = Table(
        title="[bold]Available Benchmarks[/bold]",
        border_style="bright_blue",
        title_style="bold cyan",
    )
    bench_table.add_column("Name", style="cyan", no_wrap=True)
    bench_table.add_column("Category", style="white")
    bench_table.add_column("Description")
    for name, info in BENCHMARKS.items():
        bench_table.add_row(name, info["category"], info["description"])
    console.print(bench_table)

    backend_table = Table(
        title="[bold]Available Backends[/bold]",
        border_style="bright_blue",
        title_style="bold cyan",
    )
    backend_table.add_column("Name", style="cyan", no_wrap=True)
    backend_table.add_column("Description")
    for name, desc in BACKENDS.items():
        backend_table.add_row(name, desc)
    console.print(backend_table)


if __name__ == "__main__":
    main()
