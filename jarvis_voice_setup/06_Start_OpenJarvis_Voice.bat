@echo off
cd /d "%~dp0.."
where uv >nul 2>&1
if errorlevel 1 (
  echo Install uv first: https://docs.astral.sh/uv/
  pause
  exit /b 1
)
echo Start 02_Start_Offline_Voice.bat in ANOTHER window before this step.
uv run jarvis chat --voice
if errorlevel 1 (
  echo OpenJarvis failed to start. Try: uv sync --extra voice
  pause
)
