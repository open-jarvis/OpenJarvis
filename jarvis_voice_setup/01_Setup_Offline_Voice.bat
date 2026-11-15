@echo off
setlocal
cd /d "%~dp0"
set "VOICEDIR=%USERPROFILE%\.openjarvis\voices"
set "VENV=%USERPROFILE%\.openjarvis\offline-voice-venv"
echo.
echo JARVIS - Installing free local British voice
echo All speech generation stays on your computer.
echo.
where uv >nul 2>&1
if errorlevel 1 (
  echo uv is missing. Please run 00_INSTALL_AND_START_JARVIS.bat first.
  pause
  exit /b 1
)
uv python install 3.11
if errorlevel 1 goto :failed
if not exist "%VENV%\Scripts\python.exe" (
  uv venv --python 3.11 "%VENV%"
  if errorlevel 1 goto :failed
)
"%VENV%\Scripts\python.exe" -c "import sys; assert sys.version_info[:2] == (3,11), 'Requires isolated Python 3.11'"
if errorlevel 1 (
  echo Existing voice environment uses the wrong Python version.
  echo Rename "%VENV%" and run this setup again.
  pause
  exit /b 1
)
uv pip install --python "%VENV%\Scripts\python.exe" piper-tts
if errorlevel 1 goto :failed
if not exist "%VOICEDIR%" mkdir "%VOICEDIR%"
if not exist "%VOICEDIR%\en_GB-alan-medium.onnx" goto :download
if not exist "%VOICEDIR%\en_GB-alan-medium.onnx.json" goto :download
goto :model_ready
:download
"%VENV%\Scripts\python.exe" -m piper.download_voices en_GB-alan-medium --data-dir "%VOICEDIR%"
if errorlevel 1 goto :failed
:model_ready
if not exist "%VOICEDIR%\en_GB-alan-medium.onnx" goto :failed
if not exist "%VOICEDIR%\en_GB-alan-medium.onnx.json" goto :failed
echo.
echo [SUCCESS] Free offline British voice is installed.
exit /b 0
:failed
echo.
echo [ERROR] Offline voice installation could not finish.
echo No paid speech provider has been enabled.
pause
exit /b 1
