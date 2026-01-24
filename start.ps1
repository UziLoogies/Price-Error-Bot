# Price Error Bot Startup Script
# Automatically kills any existing process on the configured port, then starts the bot

$port = 8001
$host_addr = "0.0.0.0"

# Helper function: Check if port is in use (only LISTENING state matters)
function Test-PortInUse {
    param([int]$Port)
    try {
        # Only check for LISTEN state - TIME_WAIT doesn't block new connections
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return $null -ne $connection
    } catch {
        # Fallback to netstat if Get-NetTCPConnection fails
        $netstat = netstat -ano | Select-String ":$Port\s+.*LISTENING"
        return $null -ne $netstat
    }
}

# Helper function: Kill process using port
function Kill-PortProcess {
    param([int]$Port)
    $killed = $false
    
    # Method 1: Use Get-NetTCPConnection
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
        if ($connections) {
            # Get unique process IDs (filter out system process 0)
            $pids = $connections | Where-Object { $_.OwningProcess -gt 0 } | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($processId in $pids) {
                try {
                    $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
                    if ($proc) {
                        Write-Host "Killing $($proc.ProcessName) (PID: $processId)..." -ForegroundColor Yellow
                        Stop-Process -Id $processId -Force -ErrorAction Stop
                        $killed = $true
                    }
                } catch {
                    # Try taskkill as fallback
                    taskkill /PID $processId /F 2>$null
                    $killed = $true
                }
            }
        }
    } catch {
        # Ignore errors
    }
    
    # Method 2: Use netstat as fallback
    if (-not $killed) {
        $netstat = netstat -ano | Select-String ":$Port\s+.*LISTENING"
        if ($netstat) {
            foreach ($line in $netstat) {
                $parts = ($line -split '\s+')
                $processId = $parts[-1]
                if ($processId -match '^\d+$' -and [int]$processId -gt 0) {
                    Write-Host "Killing PID $processId (netstat)..." -ForegroundColor Yellow
                    taskkill /PID $processId /F 2>$null
                    $killed = $true
                }
            }
        }
    }
    
    # Method 3: Kill all python processes as last resort
    if (-not $killed) {
        Write-Host "Killing all Python processes..." -ForegroundColor Yellow
        Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        $killed = $true
    }
    
    return $killed
}

# Helper function: Wait for port to be free
function Wait-ForPortFree {
    param([int]$Port, [int]$TimeoutSeconds = 10)
    $elapsed = 0
    while ((Test-PortInUse -Port $Port) -and ($elapsed -lt $TimeoutSeconds)) {
        Start-Sleep -Milliseconds 500
        $elapsed += 0.5
    }
    return -not (Test-PortInUse -Port $Port)
}

# Display header
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "       Price Error Bot Startup         " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is available
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Python is not installed or not in PATH" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python found: $pythonVersion" -ForegroundColor Green

# Check if Docker containers are running
Write-Host ""
Write-Host "Checking Docker containers..." -ForegroundColor Cyan
$postgresRunning = docker ps --filter "name=price_bot_postgres" --format "{{.Names}}" 2>$null
$redisRunning = docker ps --filter "name=price_bot_redis" --format "{{.Names}}" 2>$null

if (-not $postgresRunning) {
    Write-Host "[WARN] PostgreSQL container not running. Starting..." -ForegroundColor Yellow
    docker compose up -d postgres 2>$null
    Start-Sleep -Seconds 3
}
if (-not $redisRunning) {
    Write-Host "[WARN] Redis container not running. Starting..." -ForegroundColor Yellow
    docker compose up -d redis 2>$null
    Start-Sleep -Seconds 2
}

Write-Host "[OK] Database containers ready" -ForegroundColor Green

# Check and free port if in use
Write-Host ""
Write-Host "Checking port $port..." -ForegroundColor Cyan

if (Test-PortInUse -Port $port) {
    Write-Host "[WARN] Port $port is in use" -ForegroundColor Yellow
    Kill-PortProcess -Port $port
    
    Write-Host "Waiting for port to be freed..." -ForegroundColor Yellow
    $portFreed = Wait-ForPortFree -Port $port -TimeoutSeconds 10
    
    if (-not $portFreed) {
        Write-Host "[ERROR] Could not free port $port after 10 seconds" -ForegroundColor Red
        Write-Host "Please manually kill the process using:" -ForegroundColor Yellow
        Write-Host "  Get-NetTCPConnection -LocalPort $port | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force }" -ForegroundColor White
        exit 1
    }
}

Write-Host "[OK] Port $port is available" -ForegroundColor Green

# Start the bot
Write-Host ""
Write-Host "Starting Price Error Bot on http://${host_addr}:${port}..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

python -c "import uvicorn; from src.main import app; uvicorn.run(app, host='$host_addr', port=$port)"
