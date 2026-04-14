@echo off
title Jarvis AI
cd /d "C:\Users\Methu\OpenJarvis"
echo ================================
echo        Jarvis AI - Gemma 3 4B
echo ================================
echo.
set /p question="Spor Jarvis: "
echo.
call "C:\Users\Methu\OpenJarvis\.venv\Scripts\activate.bat"
jarvis ask "%question%"
echo.
pause
