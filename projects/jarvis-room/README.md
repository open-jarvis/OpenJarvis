# J.A.R.V.I.S. — Sala Temática

Projeto de desenvolvimento de um assistente inteligente local para uma sala
temática universitária.

## Objetivo

Integrar inteligência artificial local, automação, interfaces gráficas,
comandos de voz, sensores e dispositivos IoT em uma experiência inspirada
no conceito J.A.R.V.I.S.

## Arquitetura planejada

- OpenJarvis — agente e orquestração
- Ollama — inferência local
- Home Assistant — automação da sala
- MCP — integração entre IA e ferramentas
- Faster-Whisper — reconhecimento de voz
- TTS local — síntese de voz
- ESP32 / ESPHome / WLED — dispositivos IoT
- Frigate — visão computacional e presença

## Interfaces

### Monitor 1

Interface visual e interativa do J.A.R.V.I.S.

Estados planejados:

- IDLE
- OUVINDO
- PENSANDO
- EXECUTANDO
- FALANDO
- ERRO

### Monitor 2

Dashboard operacional contendo:

- temperatura;
- umidade;
- ar-condicionado;
- luzes;
- LEDs;
- televisores;
- presença;
- sensores;
- status dos serviços.

## Ambiente de desenvolvimento

Desenvolvimento:

Windows + WSL2 + Ubuntu.

Produção futura:

Linux nativo.

## Estado atual

A infraestrutura inicial foi validada.

O modelo `jarvis-dev-lite` está sendo utilizado temporariamente para
desenvolvimento e validação da arquitetura.

Modelos maiores serão avaliados posteriormente para a máquina definitiva
da Sala Temática.
