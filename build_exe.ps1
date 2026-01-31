# Price Error Bot - Desktop Application Builder
# Builds a standalone .exe using PyInstaller

param(
    [switch]$Clean,
    [switch]$Debug,
    [switch]$SkipDeps
)

$ErrorActionPreference = "Stop"

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

# ============================================================================
# MAIN BUILD PROCESS
# ============================================================================

Write-Header "Price Error Bot Desktop App Builder"

# Check if we're in the right directory
if (-not (Test-Path "launcher.py")) {
    Write-Error "launcher.py not found. Please run this script from the project root."
    exit 1
}

if (-not (Test-Path "launcher.spec")) {
    Write-Error "launcher.spec not found. Please run this script from the project root."
    exit 1
}

# Activate virtual environment
$venvActivate = ".\venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    Write-Step "Activating virtual environment..."
    & $venvActivate
    Write-Success "Virtual environment activated"
} else {
    Write-Warning "Virtual environment not found. Using system Python."
}

# Install/update dependencies
if (-not $SkipDeps) {
    Write-Step "Installing build dependencies..."
    
    # Install pywebview if not present
    $ErrorActionPreference = "SilentlyContinue"
    $null = pip show pywebview 2>$null
    $webviewInstalled = $LASTEXITCODE -eq 0
    $ErrorActionPreference = "Stop"
    
    if (-not $webviewInstalled) {
        Write-Step "Installing pywebview..."
        pip install pywebview --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to install pywebview"
            exit 1
        }
    }
    
    # Install psutil if not present
    $ErrorActionPreference = "SilentlyContinue"
    $null = pip show psutil 2>$null
    $psutilInstalled = $LASTEXITCODE -eq 0
    $ErrorActionPreference = "Stop"
    
    if (-not $psutilInstalled) {
        Write-Step "Installing psutil..."
        pip install psutil --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to install psutil"
            exit 1
        }
    }
    
    # Install pyinstaller if not present
    $ErrorActionPreference = "SilentlyContinue"
    $null = pip show pyinstaller 2>$null
    $pyinstallerInstalled = $LASTEXITCODE -eq 0
    $ErrorActionPreference = "Stop"
    
    if (-not $pyinstallerInstalled) {
        Write-Step "Installing PyInstaller..."
        $ErrorActionPreference = "SilentlyContinue"
        pip install pyinstaller --quiet 2>&1 | Out-Null
        $ErrorActionPreference = "Stop"
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to install PyInstaller"
            exit 1
        }
    }
    
    Write-Success "Build dependencies ready"
}

# Function to stop running PriceErrorBot.exe
function Stop-ExistingExe {
    $exePath = "dist\PriceErrorBot.exe"
    if (Test-Path $exePath) {
        $processes = Get-Process -Name "PriceErrorBot" -ErrorAction SilentlyContinue
        if ($processes) {
            Write-Step "Stopping running PriceErrorBot.exe..."
            foreach ($proc in $processes) {
                try {
                    Stop-Process -Id $proc.Id -Force -ErrorAction Stop
                    Write-Host "    Stopped process $($proc.Id)" -ForegroundColor Gray
                } catch {
                    Write-Warning "Could not stop process $($proc.Id): $_"
                }
            }
            # Wait a moment for file handles to release
            Start-Sleep -Seconds 2
        }
        
        # Try to remove the file if it exists
        try {
            if (Test-Path $exePath) {
                Remove-Item -Path $exePath -Force -ErrorAction Stop
                Write-Success "Removed existing executable"
            }
        } catch {
            Write-Warning "Could not remove existing executable (may be locked): $_"
            Write-Info "You may need to close the application manually and try again"
        }
    }
}

# Clean previous builds
if ($Clean) {
    Write-Step "Cleaning previous builds..."
    
    # Stop running exe first
    Stop-ExistingExe
    
    if (Test-Path "build") {
        Remove-Item -Recurse -Force "build"
    }
    if (Test-Path "dist") {
        Remove-Item -Recurse -Force "dist"
    }
    
    Write-Success "Previous builds cleaned"
} else {
    # Even without --Clean, stop existing exe to avoid permission errors
    Stop-ExistingExe
}

# Build the executable
Write-Header "Building Executable"

$pyinstallerArgs = @("launcher.spec")

if ($Clean) {
    $pyinstallerArgs += "--clean"
}

if ($Debug) {
    Write-Warning "Debug mode enabled - console will be visible"
    # Modify spec file for debug would require editing, so we just note it
}

Write-Step "Running PyInstaller..."
Write-Host ""

try {
    pyinstaller @pyinstallerArgs
    
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
} catch {
    Write-Error "Build failed: $_"
    exit 1
}

Write-Host ""

# Check if build was successful
$exePath = "dist\PriceErrorBot.exe"
if (Test-Path $exePath) {
    $exeSize = (Get-Item $exePath).Length / 1MB
    $exeSizeFormatted = "{0:N1}" -f $exeSize
    
    Write-Header "Build Successful!"
    
    Write-Success "Executable created: $exePath"
    Write-Host "    Size: $exeSizeFormatted MB" -ForegroundColor Gray
    Write-Host ""
    Write-Host "To run the application:" -ForegroundColor Cyan
    Write-Host "    .\dist\PriceErrorBot.exe" -ForegroundColor White
    Write-Host ""
    Write-Host "Requirements for running:" -ForegroundColor Yellow
    Write-Host "    - Docker Desktop must be installed and running" -ForegroundColor Gray
    Write-Host "    - WebView2 Runtime (pre-installed on Windows 10/11)" -ForegroundColor Gray
    Write-Host ""
    
    # Offer to run
    $run = Read-Host "Would you like to run the application now? (y/N)"
    if ($run -eq "y" -or $run -eq "Y") {
        Write-Host ""
        Write-Step "Starting application..."
        Start-Process $exePath
    }
} else {
    Write-Error "Build failed - executable not found"
    exit 1
}
