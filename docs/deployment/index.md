---
title: Deployment
description: Deploy OpenJarvis in production environments
---

# Deployment

OpenJarvis supports multiple deployment strategies for different environments
and scales.

## Docker

The recommended way to deploy OpenJarvis in production. Multi-stage builds
with CPU and GPU (NVIDIA CUDA, AMD ROCm) variants.

[:octicons-arrow-right-24: Docker deployment](docker.md)

## systemd (Linux)

Run OpenJarvis as a managed system service on Linux servers.

[:octicons-arrow-right-24: systemd setup](systemd.md)

## launchd (macOS)

Register OpenJarvis as a launch agent on macOS.

[:octicons-arrow-right-24: launchd setup](launchd.md)

## API Server

Run OpenJarvis as an OpenAI-compatible HTTP server via `jarvis serve`.

[:octicons-arrow-right-24: API server guide](api-server.md)

## Cloud Provider API Keys

Configure API keys for OpenAI, Anthropic, Google Gemini, Groq, DeepSeek, OpenRouter, Cerebras, SambaNova, Kimi, and more.

[:octicons-arrow-right-24: Provider API keys](providers.md)
