@echo off
setlocal
set "VENV=%USERPROFILE%\.openjarvis\offline-voice-venv"
set "REFERENCE=%USERPROFILE%\.openjarvis\voices\jarvis_reference.wav"
if not exist "%VENV%\Scripts\python.exe" (
  echo First run 01_Setup_Offline_Voice.bat.
  pause
  exit /b 1
)
if not exist "%REFERENCE%" (
  echo Put your OWN, consented, clean voice sample here:
  echo "%REFERENCE%"
  echo The private recording is never committed to GitHub.
  pause
  exit /b 1
)
echo Installing optional offline voice cloning engine (large download).
"%VENV%\Scripts\python.exe" -m pip install chatterbox-tts
if errorlevel 1 (
  echo Clone install failed. Piper will continue to work.
  pause
  exit /b 1
)
echo.
echo To use clone, set OPENJARVIS_ENABLE_VOICE_CLONE=1 before starting voice_server.py
echo Use 03_Start_Cloned_Voice.bat for this.
pause
