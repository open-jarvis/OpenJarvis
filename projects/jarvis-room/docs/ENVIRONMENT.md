# Ambiente de Desenvolvimento

## Sistema

- Windows
- WSL2
- Ubuntu 24.04.5 LTS

## Ferramentas

- VS Code 1.140.0
- Python 3.11.17
- uv 0.12.23
- Node.js 24.21.0
- npm 11.19.0
- Rust 1.99.0
- Docker Desktop / Engine 29.5.3
- Ollama 0.40.0

## Memória WSL

- RAM disponível ao WSL: aproximadamente 3.78 GiB
- Swap: 4 GiB

Configuração Windows:

```ini
[wsl2]
swap=4GB
```

## Ollama

Modelo de desenvolvimento estável:

`jarvis-dev-lite`

Base:

`qwen3.5:0.8b`

Configuração aproximada:

- CPU only
- num_ctx=2048
- num_predict=256

O modelo é adequado para validar arquitetura e integrações, mas apresentou
limitações de qualidade factual.

## OpenJarvis

OpenJarvis compilado a partir do código-fonte.

Validações concluídas:

- extensão Rust;
- REST API;
- Ollama;
- faster-whisper;
- Node.js;
- configuração local.

## Observação

O OpenJarvis utiliza atualmente contexto Ollama de 16384 tokens por padrão.
Na máquina de desenvolvimento, os testes devem utilizar:

```bash
JARVIS_NUM_CTX=2048
```

quando necessário para reduzir consumo de memória.

O modelo de 2B apresentou OOM antes da expansão do swap e deverá ser
reavaliado posteriormente.
