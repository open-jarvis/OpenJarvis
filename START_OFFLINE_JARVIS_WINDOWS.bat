@echo off
setlocal
title OFFLINE JARVIS - Installer
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0jarvis_voice_setup\one_click_windows.ps1"
if errorlevel 1 (
  echo.
  echo Jarvis setup hit an error. Please capture the last red message.
)
pause
