"""Rich-formatted error hints for common CLI failure modes（已中文化）。"""

from __future__ import annotations

from typing import Optional


def hint_no_config() -> str:
    """沒找到設定檔時的提示。"""
    return (
        "[yellow]提示：[/yellow]找不到設定檔。\n"
        "  跑 [bold]jarvis init[/bold] 會偵測硬體並產生 "
        "[cyan]~/.openjarvis/config.toml[/cyan]。\n"
        "  或跑 [bold]jarvis quickstart[/bold] 走互動式設定流程。"
    )


def hint_no_engine(engine_name: Optional[str] = None) -> str:
    """推論引擎連不到時的提示。"""
    name = engine_name or "ollama"
    if name == "mlx":
        return (
            "[yellow]提示：[/yellow]連不到 MLX 推論伺服器。\n"
            "  檢查是否在跑："
            "[bold]launchctl print gui/$UID/com.user.openjarvis.mlx[/bold]\n"
            "  手動啟動：[bold]~/.openjarvis/start-mlx.sh[/bold]\n"
            "  跑 [bold]jarvis doctor[/bold] 檢查所有引擎。\n"
        )
    return (
        f"[yellow]提示：[/yellow]連不到引擎「{name}」。\n"
        f"  確認 {name} server 有在跑。\n"
        "  跑 [bold]jarvis doctor[/bold] 檢查所有引擎。\n"
        "  跑 [bold]jarvis quickstart[/bold] 走互動式設定流程。\n"
        "\n"
        "  [dim]要連遠端引擎：[/dim]\n"
        f"    [cyan]jarvis config set engine.{name}.host http://<遠端IP>:<port>[/cyan]\n"
        f"    [dim]或[/dim] [cyan]export OLLAMA_HOST=http://<遠端IP>:11434[/cyan]"
    )


def hint_no_model(model_name: Optional[str] = None) -> str:
    """沒有可用 model 時的提示。"""
    if model_name:
        return (
            f"[yellow]提示：[/yellow]找不到 model「{model_name}」。\n"
            f"  試試：[bold]ollama pull {model_name}[/bold]\n"
            "  跑 [bold]jarvis model list[/bold] 看現有 model。"
        )
    return (
        "[yellow]提示：[/yellow]沒有可用的 model。\n"
        "  先 pull 一個：[bold]ollama pull qwen3.5:2b[/bold]\n"
        "  跑 [bold]jarvis model list[/bold] 看現有 model。"
    )


def mining_not_running_hint(cfg: object | None, sidecar_present: bool) -> Optional[str]:
    """Mining 設定了但沒跑時的提示。"""
    if cfg is None or sidecar_present:
        return None
    return "已設定 mining 但沒在跑 — 用 `jarvis mine start` 啟動"
