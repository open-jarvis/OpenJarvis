@echo off
setlocal
cd /d "%~dp0"
set "VENV=%USERPROFILE%\.openjarvis\offline-voice-venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo Run 01_Setup_Offline_Voice.bat first.
  pause
  exit /b 1
)
"%VENV%\Scripts\python.exe" "%~dp0voice_server.py"
if errorlevel 1 pause
