# Jarvis starten - Server + Telegram Bot
# Ausfuehren: PowerShell -ExecutionPolicy Bypass -File start_jarvis.ps1

$ProjectDir = $PSScriptRoot

Write-Host ""
Write-Host "  === Jarvis wird gestartet ===" -ForegroundColor Cyan
Write-Host ""

# Jarvis Web Server starten (oeffnet automatisch den Browser)
Write-Host "[1/2] Starte Jarvis Web Server (Port 7777)..." -ForegroundColor Yellow
Start-Process -FilePath "uv" `
    -ArgumentList "run python jarvis_server.py" `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Normal

Start-Sleep -Seconds 2

# Telegram Bot starten
Write-Host "[2/2] Starte Telegram Bot..." -ForegroundColor Yellow
Start-Process -FilePath "uv" `
    -ArgumentList "run python start_telegram_bot.py" `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Normal

Write-Host ""
Write-Host "  === Jarvis laeuft! ===" -ForegroundColor Green
Write-Host ""
Write-Host "  Web:      http://localhost:7777  (oeffnet sich automatisch)" -ForegroundColor White
Write-Host "  Telegram: Schreib deinem Bot auf Telegram" -ForegroundColor White
Write-Host "  Voice:    Klicke das Mikrofon auf der Webseite" -ForegroundColor White
Write-Host ""
