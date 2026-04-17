@echo off
chcp 65001 >nul
title Jarvis AI
cd /d "C:\Users\Methu\OpenJarvis"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:loop
cls
echo ================================
echo        Jarvis AI - Gemma 3 4B
echo ================================
echo  Skriv "avslutt" for å lukke
echo ================================
echo.
set "question="
set /p question="Du: "

if /i "%question%"=="avslutt" goto :eof
if "%question%"=="" goto loop

echo.
echo Jarvis tenker...
echo.
"C:\Users\Methu\OpenJarvis\.venv\Scripts\jarvis.exe" ask "%question%"
echo.
pause
goto loop
