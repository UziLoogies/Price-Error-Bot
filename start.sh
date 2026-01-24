#!/bin/bash

# Price Error Bot Startup Script
# Automatically kills any existing process on the configured port, then starts the bot

set -e

# Configuration
PORT=8001
HOST_ADDR="0.0.0.0"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

print_step() {
    echo -e "${BLUE}[*]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[X]${NC} $1"
}

# Check if port is in use (LISTEN state)
is_port_in_use() {
    local port=$1
    # Check if any process is listening on the port
    if command -v ss &> /dev/null; then
        ss -ln | grep -q ":${port} "
    elif command -v netstat &> /dev/null; then
        netstat -ln | grep -q ":${port} "
    else
        # Fallback: try to bind to the port
        if command -v python3 &> /dev/null; then
            python3 -c "
import socket
import sys
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', $port))
    s.close()
    sys.exit(1)  # Port is free
except OSError:
    sys.exit(0)  # Port is in use
" && return 0 || return 1
        else
            return 1  # Assume in use if we can't check
        fi
    fi
}

# Kill processes using the port
kill_port_processes() {
    local port=$1
    local killed=false
    
    # Find processes using the port
    if command -v lsof &> /dev/null; then
        # Use lsof if available (most reliable)
        local pids=$(lsof -ti:$port 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            for pid in $pids; do
                if [[ -n "$pid" && "$pid" -gt 0 ]]; then
                    local proc_name=$(ps -p $pid -o comm= 2>/dev/null || echo "unknown")
                    echo -e "${YELLOW}Killing $proc_name (PID: $pid)...${NC}"
                    kill -TERM $pid 2>/dev/null || kill -KILL $pid 2>/dev/null || true
                    killed=true
                fi
            done
        fi
    elif command -v ss &> /dev/null; then
        # Use ss if lsof is not available
        local pids=$(ss -tlnp | grep ":$port " | grep -oE 'pid=[0-9]+' | cut -d= -f2 || true)
        if [[ -n "$pids" ]]; then
            for pid in $pids; do
                if [[ -n "$pid" && "$pid" -gt 0 ]]; then
                    local proc_name=$(ps -p $pid -o comm= 2>/dev/null || echo "unknown")
                    echo -e "${YELLOW}Killing $proc_name (PID: $pid)...${NC}"
                    kill -TERM $pid 2>/dev/null || kill -KILL $pid 2>/dev/null || true
                    killed=true
                fi
            done
        fi
    else
        # Fallback: kill all python processes (risky but necessary)
        print_warning "No lsof or ss available, killing all Python processes..."
        pkill -f python || true
        killed=true
    fi
    
    # Wait a moment for processes to terminate
    if [[ "$killed" == true ]]; then
        sleep 2
    fi
    
    return 0
}

# Wait for port to be free
wait_for_port_free() {
    local port=$1
    local timeout=${2:-10}
    local count=0
    
    while is_port_in_use $port && [[ $count -lt $timeout ]]; do
        sleep 1
        ((count++))
    done
    
    if is_port_in_use $port; then
        return 1
    else
        return 0
    fi
}

# Check if Docker containers are running
check_containers() {
    if ! command -v docker &> /dev/null; then
        print_warning "Docker not available, skipping container checks"
        return 0
    fi
    
    local postgres_running=$(docker ps --filter "name=price_bot_postgres" --format "{{.Names}}" 2>/dev/null || true)
    local redis_running=$(docker ps --filter "name=price_bot_redis" --format "{{.Names}}" 2>/dev/null || true)
    
    if [[ -z "$postgres_running" ]]; then
        print_warning "PostgreSQL container not running. Starting..."
        docker compose up -d postgres 2>/dev/null || {
            print_error "Failed to start PostgreSQL container"
            return 1
        }
        sleep 3
    fi
    
    if [[ -z "$redis_running" ]]; then
        print_warning "Redis container not running. Starting..."
        docker compose up -d redis 2>/dev/null || {
            print_error "Failed to start Redis container"
            return 1
        }
        sleep 2
    fi
    
    return 0
}

# Find Python command
find_python() {
    for cmd in python python3; do
        if command -v "$cmd" &> /dev/null; then
            echo "$cmd"
            return 0
        fi
    done
    return 1
}

# ============================================================================
# MAIN STARTUP
# ============================================================================

# Display header
echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}       Price Error Bot Startup         ${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# Find Python
PYTHON_CMD=$(find_python) || {
    print_error "Python is not installed or not in PATH"
    exit 1
}

# Check Python version
python_version=$($PYTHON_CMD --version 2>&1)
if [[ $? -ne 0 ]]; then
    print_error "Failed to get Python version"
    exit 1
fi
print_success "Python found: $python_version"

# Check virtual environment
if [[ ! -d "venv" ]]; then
    print_error "Virtual environment not found. Run ./install.sh first."
    exit 1
fi

# Activate virtual environment
print_step "Activating virtual environment..."
source venv/bin/activate

# Check .env file
if [[ ! -f ".env" ]]; then
    print_error ".env file not found. Run ./install.sh first."
    exit 1
fi

# Check Docker containers
echo ""
print_step "Checking Docker containers..."
if ! check_containers; then
    print_error "Failed to ensure Docker containers are running"
    print_step "You can:"
    print_step "  1. Start containers manually: docker compose up -d postgres redis"
    print_step "  2. Skip Docker and use external databases"
    exit 1
fi
print_success "Database containers ready"

# Check and free port if in use
echo ""
print_step "Checking port $PORT..."

if is_port_in_use $PORT; then
    print_warning "Port $PORT is in use"
    kill_port_processes $PORT
    
    print_step "Waiting for port to be freed..."
    if ! wait_for_port_free $PORT 10; then
        print_error "Could not free port $PORT after 10 seconds"
        print_step "Please manually kill the process using:"
        print_step "  lsof -ti:$PORT | xargs kill"
        exit 1
    fi
fi

print_success "Port $PORT is available"

# Start the bot
echo ""
print_step "Starting Price Error Bot on http://${HOST_ADDR}:${PORT}..."
print_step "Press Ctrl+C to stop"
echo ""

# Use the python from virtual environment
exec python -c "import uvicorn; from src.main import app; uvicorn.run(app, host='$HOST_ADDR', port=$PORT)"