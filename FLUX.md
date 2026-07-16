# Flux — assistente pessoal do senhor

Este é um fork personalizado do [OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
configurado como **Flux**: um assistente de IA local, em português, com jeito de
mordomo, que roda na sua máquina.

> O OpenJarvis é a base (o motor). **Flux** é o nome, a voz e a configuração do
> assistente — a camada que é sua.

## O que foi personalizado

| Item | Onde |
|---|---|
| Personalidade do assistente (chat/agentes) | `configs/openjarvis/personas/flux/{SOUL,MEMORY,USER}.md` |
| Voz do briefing falado (digest) | `configs/openjarvis/prompts/personas/flux.md` |
| Config pronta (Ollama + persona Flux) | `configs/openjarvis/examples/flux.toml` |
| Instalador da personalização | `scripts/setup_flux.sh` |
| Agente de exemplo (starter) | `examples/flux/flux.py` |

## Instalação (rodar localmente — recomendado)

O Flux foi feito para rodar **na sua máquina**, não em serverless (Vercel não
serve: precisa de processo persistente + inferência local). Passos:

```bash
# 1. Instale o Ollama e baixe um modelo
#    https://ollama.com
ollama pull qwen3.5:9b        # ou qwen3.5:4b numa máquina mais modesta

# 2. Instale o OpenJarvis (a partir da raiz do repo)
uv sync --extra dev

# 3. Instale a personalização do Flux (persona + config em ~/.openjarvis)
bash scripts/setup_flux.sh

# 4. Diga quem é você
$EDITOR ~/.openjarvis/personas/flux/USER.md

# 5. Converse
jarvis
```

Ou use o agente de exemplo direto:

```bash
python examples/flux/flux.py "resuma minha agenda ideal para focar hoje"
```

## Trocar o modelo

Edite `~/.openjarvis/config.toml` (ou `configs/openjarvis/examples/flux.toml`
antes de instalar) e ajuste `default_model`:

- `qwen3.5:4b` — leve e rápido
- `qwen3.5:9b` — equilíbrio (16GB+ RAM)
- `qwen3.5:35b` — melhor qualidade (32GB+ RAM)

Máquina fraca? Dá para usar a nuvem só para "pensar": veja o modo
`inference-cloud` na doc do OpenJarvis (`pyproject.toml`) e configure
`[engine] default = "cloud"` com sua API key.

## Sobre o "rebranding" completo

O nome do assistente (Flux, a voz, a config) já é seu. **Não** renomeamos o
pacote Python `openjarvis` de propósito: isso quebraria imports, o comando
`jarvis`, o `pip install` e toda a documentação — muito custo, zero ganho para
uso pessoal. Se um dia você quiser publicar como produto próprio, aí sim vale
um rename cuidadoso; me avise.

## Crédito

Construído sobre o [OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
(Stanford Hazy Research / Scaling Intelligence Lab), licença Apache 2.0.
Veja [`LICENSE`](LICENSE) e [`README.md`](README.md).
