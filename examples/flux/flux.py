#!/usr/bin/env python3
"""Flux — assistente pessoal do senhor, na linha de comando.

Ponto de partida para um agente sob medida. Use como está ou adapte:
troque os tools, o agente, ou embuta numa rotina sua.

Uso::

    python examples/flux/flux.py "que horas são boas para focar hoje?"
    python examples/flux/flux.py --agent simple "resuma este texto: ..."
    python examples/flux/flux.py --model qwen3.5:4b "..."

Pré-requisitos:
    - Ollama rodando:   ollama serve
    - Um modelo:        ollama pull qwen3.5:9b
    - (opcional) persona instalada:  bash scripts/setup_flux.sh
"""

from __future__ import annotations

import sys

import click

# Preâmbulo de identidade — garante a voz do Flux mesmo sem a persona instalada.
FLUX_PREAMBLE = (
    "Você é o Flux, assistente pessoal local do senhor. Fala português "
    "brasileiro com elegância de mordomo: educado, seco, eficiente. "
    "Trata o usuário por 'senhor', com moderação. Responde a pergunta "
    "primeiro; detalhes só se agregarem. Nunca inventa fatos.\n\n"
)


@click.command()
@click.argument("pergunta", nargs=-1, required=True)
@click.option("--model", default="qwen3.5:9b", show_default=True, help="Modelo Ollama.")
@click.option("--engine", "engine_key", default="ollama", show_default=True)
@click.option(
    "--agent",
    "agent",
    default="orchestrator",
    show_default=True,
    help="orchestrator (com ferramentas) ou simple (chat puro).",
)
def main(pergunta: tuple[str, ...], model: str, engine_key: str, agent: str) -> None:
    """Faz uma pergunta ao Flux e imprime a resposta."""
    try:
        from openjarvis import Jarvis
    except ImportError:
        click.echo(
            "Erro: openjarvis não está instalado. Rode:  uv sync --extra dev",
            err=True,
        )
        sys.exit(1)

    query = FLUX_PREAMBLE + " ".join(pergunta)
    tools = ["web_search", "file_read", "think", "calculator"]

    try:
        j = Jarvis(model=model, engine_key=engine_key)
    except Exception as exc:
        click.echo(
            f"Erro ao iniciar o Flux — {exc}\n\n"
            "Verifique se o engine está no ar. Para Ollama:\n"
            "  ollama serve\n"
            f"  ollama pull {model}",
            err=True,
        )
        sys.exit(1)

    try:
        if agent == "simple":
            resposta = j.ask(query, agent="simple")
        else:
            resposta = j.ask(query, agent=agent, tools=tools)
    except Exception as exc:
        click.echo(f"Erro durante a resposta: {exc}", err=True)
        sys.exit(1)
    finally:
        j.close()

    click.echo(resposta)


if __name__ == "__main__":
    main()
