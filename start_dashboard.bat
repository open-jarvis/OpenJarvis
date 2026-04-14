@echo off
title Jarvis Dashboard
cd /d "C:\Users\Methu\OpenJarvis\dashboard"
echo Starter Jarvis Dashboard...
start "" "http://localhost:8765"
"C:\Users\Methu\OpenJarvis\.venv\Scripts\python.exe" -m http.server 8765
