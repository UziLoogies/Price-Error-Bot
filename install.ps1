# Price Error Bot - Comprehensive Installer
# Uses Winget to install all prerequisites and set up the application
# Run this script in PowerShell as Administrator

param(
    [switch]$SkipPrerequisites,
    [switch]$SkipDocker,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

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

function Write-Info {
    param([string]$Text)
    Write-Host "    $Text" -ForegroundColor Gray
}

function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Request-Elevation {
    if (-not (Test-Administrator)) {
        Write-Warning "This script requires Administrator privileges for installing prerequisites."
        Write-Step "Requesting elevation..."
        
        $scriptPath = $MyInvocation.ScriptName
        if (-not $scriptPath) {
            $scriptPath = $PSCommandPath
        }
        
        try {
            Start-Process powershell.exe -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$scriptPath`""
            exit 0
        } catch {
            Write-Error "Failed to elevate. Please run PowerShell as Administrator."
            exit 1
        }
    }
}

function Test-WingetAvailable {
    try {
        $null = Get-Command winget -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Refresh-Path {
    Write-Step "Refreshing PATH environment..."
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Test-PythonInstalled {
    try {
        $version = python --version 2>&1
        if ($version -match "Python 3\.1[1-9]|Python 3\.[2-9]") {
            return $true
        }
        # Check for older Python 3.11+
        if ($version -match "Python 3\.11") {
            return $true
        }
        return $false
    } catch {
        return $false
    }
}

function Test-DockerInstalled {
    try {
        $null = Get-Command docker -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Test-GitInstalled {
    try {
        $null = Get-Command git -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Test-DockerRunning {
    try {
        $info = docker info 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Wait-ForDocker {
    param([int]$TimeoutSeconds = 120)
    
    Write-Step "Waiting for Docker Desktop to start..."
    $elapsed = 0
    $interval = 5
    
    while ($elapsed -lt $TimeoutSeconds) {
        if (Test-DockerRunning) {
            return $true
        }
        Write-Info "Docker not ready yet... ($elapsed/$TimeoutSeconds seconds)"
        Start-Sleep -Seconds $interval
        $elapsed += $interval
    }
    
    return $false
}

function Start-DockerDesktop {
    Write-Step "Starting Docker Desktop..."
    
    # Try common installation paths
    $dockerPaths = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
    )
    
    foreach ($path in $dockerPaths) {
        if (Test-Path $path) {
            Start-Process $path
            return $true
        }
    }
    
    # Try to start via Start Menu shortcut
    try {
        Start-Process "Docker Desktop"
        return $true
    } catch {
        return $false
    }
}

# ============================================================================
# MAIN INSTALLATION
# ============================================================================

Write-Header "Price Error Bot Installer"

Write-Host "This installer will:" -ForegroundColor White
Write-Host "  1. Install Python 3.11+ (if not installed)" -ForegroundColor Gray
Write-Host "  2. Install Docker Desktop (if not installed)" -ForegroundColor Gray
Write-Host "  3. Install Git (if not installed)" -ForegroundColor Gray
Write-Host "  4. Create Python virtual environment" -ForegroundColor Gray
Write-Host "  5. Install Python dependencies" -ForegroundColor Gray
Write-Host "  6. Install Playwright browsers" -ForegroundColor Gray
Write-Host "  7. Configure environment" -ForegroundColor Gray
Write-Host "  8. Start database containers" -ForegroundColor Gray
Write-Host "  9. Run database migrations" -ForegroundColor Gray
Write-Host " 10. Seed default categories" -ForegroundColor Gray
Write-Host ""

# Check for admin rights if installing prerequisites
if (-not $SkipPrerequisites) {
    Request-Elevation
}

# ============================================================================
# STEP 1: Check Winget
# ============================================================================

Write-Header "Step 1: Checking Windows Package Manager"

if (-not $SkipPrerequisites) {
    if (Test-WingetAvailable) {
        Write-Success "Winget is available"
    } else {
        Write-Error "Winget is not available on this system."
        Write-Info "Winget requires Windows 10 version 1709 or later."
        Write-Info "Please install App Installer from the Microsoft Store:"
        Write-Info "https://apps.microsoft.com/store/detail/app-installer/9NBLGGH4NNS1"
        exit 1
    }
}

# ============================================================================
# STEP 2: Install Python
# ============================================================================

Write-Header "Step 2: Python Installation"

if (Test-PythonInstalled) {
    $pythonVersion = python --version 2>&1
    Write-Success "Python is already installed: $pythonVersion"
} elseif (-not $SkipPrerequisites) {
    Write-Step "Installing Python 3.11..."
    try {
        winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        
        # Verify installation
        Start-Sleep -Seconds 2
        if (Test-PythonInstalled) {
            $pythonVersion = python --version 2>&1
            Write-Success "Python installed successfully: $pythonVersion"
        } else {
            Write-Warning "Python installed but not in PATH. You may need to restart PowerShell."
        }
    } catch {
        Write-Error "Failed to install Python: $_"
        Write-Info "Please install Python 3.11+ manually from https://python.org"
        exit 1
    }
} else {
    Write-Error "Python 3.11+ is required but not installed."
    exit 1
}

# ============================================================================
# STEP 3: Install Docker Desktop
# ============================================================================

Write-Header "Step 3: Docker Desktop Installation"

if (Test-DockerInstalled) {
    Write-Success "Docker is already installed"
} elseif (-not $SkipPrerequisites) {
    Write-Step "Installing Docker Desktop..."
    Write-Info "This may take several minutes..."
    try {
        winget install Docker.DockerDesktop --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        Write-Success "Docker Desktop installed"
        Write-Warning "You may need to restart your computer for Docker to work properly."
        Write-Warning "After restart, run this installer again with -SkipPrerequisites"
        
        $restart = Read-Host "Would you like to continue without restarting? (y/N)"
        if ($restart -ne "y" -and $restart -ne "Y") {
            Write-Info "Please restart your computer and run this installer again."
            exit 0
        }
    } catch {
        Write-Error "Failed to install Docker Desktop: $_"
        Write-Info "Please install Docker Desktop manually from https://docker.com"
        exit 1
    }
} else {
    Write-Error "Docker is required but not installed."
    exit 1
}

# ============================================================================
# STEP 4: Install Git (Optional)
# ============================================================================

Write-Header "Step 4: Git Installation"

if (Test-GitInstalled) {
    $gitVersion = git --version 2>&1
    Write-Success "Git is already installed: $gitVersion"
} elseif (-not $SkipPrerequisites) {
    Write-Step "Installing Git..."
    try {
        winget install Git.Git --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        Write-Success "Git installed successfully"
    } catch {
        Write-Warning "Failed to install Git. This is optional and installation will continue."
    }
} else {
    Write-Warning "Git is not installed. This is optional."
}

# ============================================================================
# STEP 5: Start Docker Desktop
# ============================================================================

Write-Header "Step 5: Starting Docker Desktop"

if (-not $SkipDocker) {
    if (Test-DockerRunning) {
        Write-Success "Docker is already running"
    } else {
        if (-not (Start-DockerDesktop)) {
            Write-Warning "Could not auto-start Docker Desktop."
            Write-Info "Please start Docker Desktop manually and press Enter to continue..."
            Read-Host
        }
        
        if (-not (Wait-ForDocker -TimeoutSeconds 120)) {
            Write-Error "Docker Desktop did not start within 2 minutes."
            Write-Info "Please ensure Docker Desktop is running and try again."
            Write-Info "You can run this installer with -SkipDocker to skip Docker checks."
            exit 1
        }
        Write-Success "Docker Desktop is running"
    }
}

# ============================================================================
# STEP 6: Create Virtual Environment
# ============================================================================

Write-Header "Step 6: Python Virtual Environment"

$venvPath = Join-Path $PSScriptRoot "venv"
$venvActivate = Join-Path $venvPath "Scripts\Activate.ps1"

if ((Test-Path $venvPath) -and -not $Force) {
    Write-Success "Virtual environment already exists"
} else {
    Write-Step "Creating virtual environment..."
    try {
        python -m venv venv
        Write-Success "Virtual environment created"
    } catch {
        Write-Error "Failed to create virtual environment: $_"
        exit 1
    }
}

# Activate virtual environment
Write-Step "Activating virtual environment..."
try {
    & $venvActivate
    Write-Success "Virtual environment activated"
} catch {
    Write-Error "Failed to activate virtual environment: $_"
    exit 1
}

# ============================================================================
# STEP 7: Install Python Dependencies
# ============================================================================

Write-Header "Step 7: Python Dependencies"

Write-Step "Upgrading pip..."
python -m pip install --upgrade pip --quiet

Write-Step "Installing project dependencies..."
Write-Info "This may take a few minutes..."
try {
    pip install -e . --quiet
    Write-Success "Dependencies installed"
} catch {
    Write-Error "Failed to install dependencies: $_"
    exit 1
}

# ============================================================================
# STEP 8: Install Playwright Browsers
# ============================================================================

Write-Header "Step 8: Playwright Browser Installation"

Write-Step "Installing Chromium browser for Playwright..."
try {
    playwright install chromium
    Write-Success "Playwright browsers installed"
} catch {
    Write-Warning "Failed to install Playwright browsers. You can install manually with: playwright install chromium"
}

# ============================================================================
# STEP 9: Environment Configuration
# ============================================================================

Write-Header "Step 9: Environment Configuration"

$envFile = Join-Path $PSScriptRoot ".env"
$envExample = Join-Path $PSScriptRoot ".env.example"

if ((Test-Path $envFile) -and -not $Force) {
    Write-Success ".env file already exists"
} else {
    Write-Step "Creating .env file..."
    
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
    } else {
        # Create default .env file
        $envContent = @"
# Price Error Bot Configuration
# Generated by install.ps1

# Database
DATABASE_URL=postgresql+asyncpg://price_bot:localdev@localhost:5432/price_bot

# Redis
REDIS_URL=redis://localhost:6379/0

# Application
APP_HOST=0.0.0.0
APP_PORT=8001
DEBUG=false
LOG_LEVEL=INFO

# Discord Webhook (optional - configure in Settings tab)
DISCORD_WEBHOOK_URL=

# Keepa API (optional)
KEEPA_API_KEY=

# Scheduler Settings
FETCH_INTERVAL_MINUTES=5
DEDUPE_TTL_HOURS=12
COOLDOWN_MINUTES=60

# Rate Limiting
MAX_CONCURRENT_REQUESTS=10
REQUESTS_PER_SECOND=2.0

# Headless Browser
HEADLESS_BROWSER_TIMEOUT=30
"@
        $envContent | Out-File -FilePath $envFile -Encoding utf8
    }
    Write-Success ".env file created"
    
    # Prompt for Discord webhook
    Write-Host ""
    Write-Host "Would you like to configure a Discord webhook now? (optional)" -ForegroundColor Yellow
    $webhookUrl = Read-Host "Discord Webhook URL (press Enter to skip)"
    
    if ($webhookUrl) {
        (Get-Content $envFile) -replace 'DISCORD_WEBHOOK_URL=.*', "DISCORD_WEBHOOK_URL=$webhookUrl" | Set-Content $envFile
        Write-Success "Discord webhook configured"
    }
}

# ============================================================================
# STEP 10: Start Database Containers
# ============================================================================

Write-Header "Step 10: Database Containers"

if (-not $SkipDocker) {
    Write-Step "Starting PostgreSQL and Redis containers..."
    try {
        docker compose up -d postgres redis
        Write-Success "Database containers started"
        
        # Wait for containers to be healthy
        Write-Step "Waiting for containers to be ready..."
        Start-Sleep -Seconds 5
        
        $retries = 0
        $maxRetries = 12
        while ($retries -lt $maxRetries) {
            $pgHealth = docker inspect --format='{{.State.Health.Status}}' price_bot_postgres 2>$null
            if ($pgHealth -eq "healthy") {
                break
            }
            Write-Info "Waiting for PostgreSQL... ($retries/$maxRetries)"
            Start-Sleep -Seconds 5
            $retries++
        }
        
        Write-Success "Database containers are ready"
    } catch {
        Write-Error "Failed to start database containers: $_"
        Write-Info "Make sure Docker Desktop is running and try again."
        exit 1
    }
} else {
    Write-Warning "Skipping Docker container startup (--SkipDocker flag)"
}

# ============================================================================
# STEP 11: Database Migrations
# ============================================================================

Write-Header "Step 11: Database Migrations"

Write-Step "Running database migrations..."
try {
    alembic upgrade head
    Write-Success "Database migrations completed"
} catch {
    Write-Error "Failed to run migrations: $_"
    Write-Info "Make sure the database container is running and try: alembic upgrade head"
    exit 1
}

# ============================================================================
# STEP 12: Seed Categories
# ============================================================================

Write-Header "Step 12: Seeding Categories"

Write-Step "Seeding default store categories..."
try {
    python scripts/seed_categories.py
    Write-Success "Categories seeded"
} catch {
    Write-Warning "Failed to seed categories. You can run manually: python scripts/seed_categories.py"
}

# ============================================================================
# INSTALLATION COMPLETE
# ============================================================================

Write-Header "Installation Complete!"

Write-Host "The Price Error Bot has been successfully installed!" -ForegroundColor Green
Write-Host ""
Write-Host "To start the bot:" -ForegroundColor White
Write-Host "  .\start.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "Or manually:" -ForegroundColor White
Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor Gray
Write-Host "  python -c `"import uvicorn; from src.main import app; uvicorn.run(app, host='0.0.0.0', port=8001)`"" -ForegroundColor Gray
Write-Host ""
Write-Host "Dashboard URL: http://localhost:8001" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Start the bot with .\start.ps1" -ForegroundColor Gray
Write-Host "  2. Open http://localhost:8001 in your browser" -ForegroundColor Gray
Write-Host "  3. Go to Settings tab to configure Discord webhook" -ForegroundColor Gray
Write-Host "  4. Go to Categories tab to manage store categories" -ForegroundColor Gray
Write-Host ""

# Offer to start the bot
$startNow = Read-Host "Would you like to start the bot now? (Y/n)"
if ($startNow -eq "" -or $startNow -eq "y" -or $startNow -eq "Y") {
    Write-Host ""
    & (Join-Path $PSScriptRoot "start.ps1")
}
