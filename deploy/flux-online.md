# Deixar o Flux online

Objetivo: acessar o Flux de qualquer lugar (celular, outro PC), não só no
`localhost` da máquina onde ele roda.

> **Por que não Vercel/serverless?** O Flux é um processo persistente que roda
> inferência de LLM (Ollama) e tem daemon/agendador. Serverless não roda isso.
> Ele precisa de uma máquina de verdade sempre ligada.

Você tem uma máquina com 64GB de RAM — ótima para rodar o modelo localmente.
Há dois caminhos, do mais simples ao mais robusto.

---

## Caminho A — Máquina de casa + túnel (recomendado para começar)

O Flux roda na sua máquina (rápido, privado, de graça) e um **túnel** dá a ele
uma URL HTTPS acessível de fora, **sem abrir portas** no seu roteador.

Vantagens: grátis, privado, inferência local rápida.
Limitação: só funciona com a máquina ligada.

### 1. Suba o Flux localmente

```bash
ollama serve &
jarvis serve                     # sobe a API em 127.0.0.1:8000
```

### 2a. Opção Tailscale (mais simples, rede privada)

Bom se o acesso é só seu (seus próprios aparelhos).

```bash
# instale em https://tailscale.com/download nos dois aparelhos
tailscale up
# acesse http://<nome-da-maquina>:8000 de qualquer aparelho na sua tailnet
```

### 2b. Opção Cloudflare Tunnel (URL pública HTTPS)

Bom se você quer uma URL de verdade. **Ative uma API key antes**, pois a API
fica alcançável publicamente:

```bash
jarvis auth generate-key          # gere e guarde a chave (header Authorization)
# instale o cloudflared: https://developers.cloudflare.com/cloudflare-tunnel/
cloudflared tunnel --url http://localhost:8000
# ele imprime uma URL https://<algo>.trycloudflare.com
```

### 3. Manter rodando (mesmo após reboot)

O repo já traz os arquivos de serviço:

- **Linux:** `deploy/systemd/openjarvis.service`
- **macOS:** `deploy/launchd/com.openjarvis.plist`
- **Windows:** `deploy/windows/jarvis-service.ps1`

---

## Caminho B — Servidor 24/7 (VPS)

Para o Flux ficar online **mesmo com seu PC desligado**. Custa dinheiro e você
perde a inferência local (VPS comum não tem GPU).

Como um VPS não roda modelos grandes bem, use o **modo nuvem** para o "cérebro"
(o VPS fica leve e chama a API da Anthropic/OpenAI):

```toml
# no config.toml do servidor
[engine]
default = "cloud"

[intelligence]
default_model = "claude-sonnet-5"   # ou outro; precisa da API key do provedor
```

Deploy com Docker (o repo já traz o compose):

```bash
# no VPS, com a API key em /etc/openjarvis/env  ->  OPENJARVIS_API_KEY=...
docker compose -f deploy/docker/docker-compose.yml up -d
```

E ponha um domínio/HTTPS na frente (Caddy/Nginx ou Cloudflare Tunnel).

---

## Qual escolher?

| | Caminho A (casa + túnel) | Caminho B (VPS) |
|---|---|---|
| Custo | Grátis | ~US$ 5–20/mês + API |
| Privacidade | Alta (roda local) | Menor (nuvem) |
| Sempre online | Só com PC ligado | Sim, 24/7 |
| Velocidade | Rápida (seus 64GB) | Depende da API |

**Recomendação:** comece pelo **Caminho A** (Tailscale é o mais rápido de pôr de
pé). Se depois precisar de 24/7 independente do seu PC, migramos para o B.
