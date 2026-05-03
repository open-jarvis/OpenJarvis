param(
    [string]$Voice = "nova"
)

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Serena Local Operator" -ForegroundColor Cyan
Write-Host " Dr Piet Muller's AI assistant" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Set-Location "C:\Users\Kyle\Serena"

Write-Host "[1/4] Checking Serena..." -ForegroundColor Yellow
uv run serena doctor

Write-Host ""
Write-Host "[2/4] Starting voice greeting..." -ForegroundColor Yellow
uv run serena speak --voice $Voice "Serena online. Voice system ready. Brain, speech, and local operator systems are available."

Write-Host ""
Write-Host "[3/4] Available commands:" -ForegroundColor Yellow
Write-Host "  uv run serena ask `"Who are you?`""
Write-Host "  uv run serena say `"Who are you?`""
Write-Host "  uv run serena speak `"Serena online.`""
Write-Host "  uv run serena listen --list-devices"
Write-Host "  uv run serena voice --seconds 5 --device <mic-index>"
Write-Host ""

Write-Host "[4/4] Serena startup complete." -ForegroundColor Green
Write-Host ""
