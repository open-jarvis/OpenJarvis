@echo off
setlocal
set "VENV=%USERPROFILE%\.openjarvis\offline-voice-venv"
set "REFERENCE=%USERPROFILE%\.openjarvis\voices\jarvis_reference.wav"
where uv >nul 2>&1
if errorlevel 1 (
  echo uv is missing. Run 00_INSTALL_AND_START_JARVIS.bat first.
  pause
  exit /b 1
)
if not exist "%VENV%\Scripts\python.exe" (
  echo First run 01_Setup_Offline_Voice.bat.
  pause
  exit /b 1
)
if not exist "%REFERENCE%" (
  echo.
  echo To copy YOUR voice locally, place a clean WAV sample here:
  echo "%REFERENCE%"
  echo.
  echo Never upload private voice recordings to your public GitHub repository.
  pause
  exit /b 1
)
echo Installing optional offline voice clone. This may download large free models.
uv pip install --python "%VENV%\Scripts\python.exe" chatterbox-tts
if errorlevel 1 (
  echo.
  echo The optional clone failed to install. Free Piper speech still works.
  pause
  exit /b 1
)
echo.
echo Clone installed. Run 04_Start_Cloned_Voice.bat to try it.
pause
exit /b 0
