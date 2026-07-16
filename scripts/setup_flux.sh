#!/usr/bin/env bash
# Instala a personalização do Flux nos diretórios do OpenJarvis (~/.openjarvis).
# Idempotente: pode rodar de novo sem estragar nada existente.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${OPENJARVIS_CONFIG_DIR:-$HOME/.openjarvis}"
PERSONA_SRC="$REPO_ROOT/configs/openjarvis/personas/flux"
PERSONA_DST="$CONFIG_DIR/personas/flux"
PRESET_SRC="$REPO_ROOT/configs/openjarvis/examples/flux.toml"
CONFIG_DST="$CONFIG_DIR/config.toml"

echo "==> Flux setup"
echo "    Config dir: $CONFIG_DIR"

# 1. Persona (SOUL/MEMORY/USER)
mkdir -p "$PERSONA_DST"
for f in SOUL.md MEMORY.md USER.md; do
  if [ -f "$PERSONA_DST/$f" ]; then
    echo "    mantém  personas/flux/$f (já existe)"
  else
    cp "$PERSONA_SRC/$f" "$PERSONA_DST/$f"
    echo "    copia   personas/flux/$f"
  fi
done

# 2. Config principal
if [ -f "$CONFIG_DST" ]; then
  echo "    ATENÇÃO: $CONFIG_DST já existe — não sobrescrito."
  echo "             Para usar o preset do Flux, copie à mão:"
  echo "             cp \"$PRESET_SRC\" \"$CONFIG_DST\""
else
  mkdir -p "$CONFIG_DIR"
  cp "$PRESET_SRC" "$CONFIG_DST"
  echo "    copia   config.toml (preset do Flux)"
fi

echo "==> Pronto. Edite $PERSONA_DST/USER.md com seus dados e rode: jarvis"
