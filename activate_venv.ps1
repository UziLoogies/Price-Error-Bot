# Helper script to activate the virtual environment
# Usage (dot-source to persist in your session): . .\activate_venv.ps1
# Note: Running .\activate_venv.ps1 without dot-sourcing only activates within the script scope

$ErrorActionPreference = "Stop"

$venvPath = Join-Path $PSScriptRoot "venv"
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"

if (-not (Test-Path $venvPath)) {
    Write-Host "Virtual environment not found. Creating it..." -ForegroundColor Yellow
    python -m venv $venvPath
    Write-Host "Virtual environment created successfully!" -ForegroundColor Green
}

if (-not (Test-Path $activateScript)) {
    Write-Host "Error: Activation script not found at $activateScript" -ForegroundColor Red
    return
}

Write-Host "Activating virtual environment..." -ForegroundColor Cyan
Write-Host "  . .\activate_venv.ps1" -ForegroundColor Cyan
Write-Host "Tip: Dot-source the script to persist activation in your session" -ForegroundColor Yellow
Write-Host ""
try {
    # Dot-source the activation script to persist in caller's session
    . $activateScript
    Write-Host "Virtual environment activated successfully!" -ForegroundColor Green
    Write-Host "Python location: $(python -c 'import sys; print(sys.executable)')" -ForegroundColor Gray
} catch {
    Write-Host "Error activating virtual environment: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "If you see an execution policy error, run:" -ForegroundColor Yellow
    Write-Host "  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Cyan
    return
}
