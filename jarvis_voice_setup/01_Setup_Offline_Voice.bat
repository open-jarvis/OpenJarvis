@echo off
setlocal
cd /d "%~dp0"
set "VOICEDIR=%USERPROFILE%\.openjarvis\voices"
set "VENV=%USERPROFILE%\.openjarvis\offline-voice-venv"
echo Installing FREE LOCAL Jarvis speech (not ElevenLabs).
where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher missing. Install Python 3.11 from python.org.
  pause
  exit /b 1
)
py -3.11 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.11 is required for the optional voice clone.
  echo Get Python 3.11 from https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist "%VENV%\Scripts\python.exe" (
  py -3.11 -m venv "%VENV%"
  if errorlevel 1 goto :failed
)
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"%VENV%\Scripts\python.exe" -m pip install piper-tts
if errorlevel 1 goto :failed
if not exist "%VOICEDIR%" mkdir "%VOICEDIR%"
if not exist "%VOICEDIR%\en_GB-alan-medium.onnx" (
  "%VENV%\Scripts\python.exe" -m piper.download_voices --data-dir "%VOICEDIR%" en_GB-alan-medium
  if errorlevel 1 goto :failed
)
echo.
echo Setup complete. Now run 02_Start_Offline_Voice.bat
pause
exit /b 0
:failed
echo Voice setup failed. No paid voice services were enabled.
pause
exit /b 1
