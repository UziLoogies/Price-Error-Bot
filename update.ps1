# Price Error Bot - Update Script
# Updates the application with latest code, dependencies, and migrations

param(
    [switch]$SkipMigrations,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Continue"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Text)
    Write-Host "[*] $Text" -ForegroundColor White
}

function Write-Success {
    param([string]$Text)
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Text)
    Write-Host "[!] $Text" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Text)
    Write-Host "[X] $Text" -ForegroundColor Red
}

# ============================================================================
# MAIN UPDATE PROCESS
# ============================================================================

Write-Header "Updating Price Error Bot"

# Step 1: Pull latest code
Write-Step "Pulling latest code from git..."
try {
    $gitStatus = git status --porcelain 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Git not available or not a git repository. Skipping git pull."
    } else {
        $hasChanges = $gitStatus -ne ""
        if ($hasChanges) {
            Write-Warning "You have uncommitted changes. Consider committing or stashing them first."
            $response = Read-Host "Continue anyway? (y/N)"
            if ($response -ne "y" -and $response -ne "Y") {
                Write-Error "Update cancelled by user"
                exit 1
            }
        }
        
        git pull
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Code updated from git"
        } else {
            Write-Warning "Git pull failed or no updates available"
        }
    }
} catch {
    Write-Warning "Could not pull from git: $_"
}

# Step 2: Activate virtual environment
Write-Step "Activating virtual environment..."
$venvPath = Join-Path $PSScriptRoot "venv"
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"

if (-not (Test-Path $activateScript)) {
    Write-Error "Virtual environment not found at $venvPath"
    Write-Step "Run .\install.ps1 first to set up the environment"
    exit 1
}

try {
    . $activateScript
    Write-Success "Virtual environment activated"
} catch {
    Write-Error "Failed to activate virtual environment: $_"
    exit 1
}

# Step 3: Update Python dependencies
Write-Step "Updating Python dependencies..."
try {
    pip install -e . --upgrade
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Dependencies updated"
    } else {
        Write-Error "Failed to update dependencies"
        exit 1
    }
} catch {
    Write-Error "Error updating dependencies: $_"
    exit 1
}

# Step 4: Run database migrations
if (-not $SkipMigrations) {
    Write-Step "Running database migrations..."
    try {
        alembic upgrade head
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Database migrations applied"
        } else {
            Write-Warning "Database migrations failed or no migrations to apply"
        }
    } catch {
        Write-Warning "Could not run migrations: $_"
    }
} else {
    Write-Step "Skipping database migrations (--SkipMigrations specified)"
}

# Step 5: Update Playwright browsers (if needed)
Write-Step "Checking Playwright browsers..."
try {
    playwright install chromium
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Playwright browsers up to date"
    } else {
        Write-Warning "Playwright browser update had issues"
    }
} catch {
    Write-Warning "Could not update Playwright browsers: $_"
}

# Step 6: Rebuild desktop app (optional)
if (-not $SkipBuild) {
    $rebuild = Read-Host "Rebuild desktop .exe? (y/N)"
    if ($rebuild -eq "y" -or $rebuild -eq "Y") {
        Write-Step "Rebuilding desktop application..."
        try {
            .\build_exe.ps1
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Desktop application rebuilt"
            } else {
                Write-Warning "Desktop application build had issues"
            }
        } catch {
            Write-Warning "Could not rebuild desktop application: $_"
        }
    }
} else {
    Write-Step "Skipping desktop app rebuild (--SkipBuild specified)"
}

# Summary
Write-Header "Update Complete"
Write-Success "Price Error Bot has been updated!"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Review any migration changes" -ForegroundColor Gray
Write-Host "  2. Restart the application: .\start.ps1" -ForegroundColor Gray
Write-Host "  3. Or run: python launcher.py" -ForegroundColor Gray
Write-Host "  4. Or run: .\dist\PriceErrorBot.exe" -ForegroundColor Gray
Write-Host ""
