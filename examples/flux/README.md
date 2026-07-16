# Flux (exemplo)

Agente de exemplo do **Flux**, o assistente pessoal personalizado deste fork.
É um ponto de partida — copie e adapte para suas próprias rotinas.

```bash
python examples/flux/flux.py "que devo priorizar hoje?"
python examples/flux/flux.py --agent simple "traduza para inglês: bom dia"
python examples/flux/flux.py --model qwen3.5:4b "..."   # modelo mais leve
```

Pré-requisitos: Ollama no ar (`ollama serve`) e um modelo (`ollama pull qwen3.5:9b`).
Veja o guia completo em [`../../FLUX.md`](../../FLUX.md).
