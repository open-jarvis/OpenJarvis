@echo off
cd /d "%~dp0.."
where uv >nul 2>&1
if errorlevel 1 (
  echo Install uv first: https://docs.astral.sh/uv/
  pause
  exit /b 1
)
uv run python jarvis_voice_setup\configure_voice.py
if errorlevel 1 (
  echo Configuration failed. Check OpenJarvis was installed.
  pause
)
