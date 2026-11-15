@echo off
setlocal
title JARVIS - Offline Voice Chat
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0jarvis_voice_setup\reopen_offline_jarvis.ps1"
if errorlevel 1 echo [ERROR] Jarvis could not start. Run START_OFFLINE_JARVIS_WINDOWS.bat to repair installation.
pause
