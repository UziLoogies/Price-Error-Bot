#!/bin/bash

# Price Error Bot - Linux Installation Script
# Installs all prerequisites and sets up the application

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
SKIP_PREREQUISITES=false
SKIP_DOCKER=false
FORCE=false
PYTHON_CMD=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-prerequisites)
            SKIP_PREREQUISITES=true
            shift
            ;;
        --skip-docker)
            SKIP_DOCKER=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --skip-prerequisites   Skip system package installation"
            echo "  --skip-docker          Skip Docker setup and containers"
            echo "  --force                Force recreate virtual environment and .env file"
            echo "  -h, --help            Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

print_header() {
    echo ""
    echo -e "${CYAN}============================================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}============================================================${NC}"
    echo ""
}

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

print_info() {
    echo -e "    $1"
}

check_root() {
    if [[ $EUID -eq 0 ]]; then
        print_warning "This script should not be run as root for security reasons."
        print_info "Please run as a regular user. Sudo will be used when needed."
        exit 1
    fi
}

detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS=$ID
        OS_VERSION=$VERSION_ID
    else
        print_error "Cannot detect operating system"
        exit 1
    fi
}

find_python() {
    # Try to find Python 3.11+ in order of preference
    for cmd in python3.12 python3.11 python3 python; do
        if command -v "$cmd" &> /dev/null; then
            version=$($cmd --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
            major=$(echo $version | cut -d. -f1)
            minor=$(echo $version | cut -d. -f2)
            
            if [[ $major -eq 3 && $minor -ge 11 ]]; then
                PYTHON_CMD=$cmd
                print_success "Found Python $version at $cmd"
                return 0
            fi
        fi
    done
    return 1
}

install_prerequisites() {
    print_step "Installing system prerequisites..."
    
    case $OS in
        ubuntu|debian)
            sudo apt update
            sudo apt install -y \
                python3 \
                python3-venv \
                python3-pip \
                git \
                curl \
                wget
            ;;
        centos|rhel|fedora)
            if command -v dnf &> /dev/null; then
                sudo dnf install -y \
                    python3 \
                    python3-venv \
                    python3-pip \
                    git \
                    curl \
                    wget
            else
                sudo yum install -y \
                    python3 \
                    python3-venv \
                    python3-pip \
                    git \
                    curl \
                    wget
            fi
            ;;
        *)
            print_warning "Unsupported OS: $OS. You may need to install prerequisites manually."
            print_info "Required packages: python3 (3.11+), python3-venv, python3-pip, git, curl, wget"
            ;;
    esac
}

install_docker() {
    print_step "Installing Docker..."
    
    case $OS in
        ubuntu|debian)
            # Install Docker using official Docker repository
            curl -fsSL https://get.docker.com -o get-docker.sh
            sudo sh get-docker.sh
            sudo usermod -aG docker $USER
            rm get-docker.sh
            
            # Install Docker Compose
            if ! command -v docker-compose &> /dev/null; then
                sudo apt install -y docker-compose-plugin
            fi
            ;;
        centos|rhel|fedora)
            # Install Docker using official Docker repository
            curl -fsSL https://get.docker.com -o get-docker.sh
            sudo sh get-docker.sh
            sudo systemctl enable docker
            sudo systemctl start docker
            sudo usermod -aG docker $USER
            rm get-docker.sh
            ;;
        *)
            print_warning "Unsupported OS for Docker installation. Please install Docker manually."
            print_info "Visit: https://docs.docker.com/engine/install/"
            ;;
    esac
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        if [[ "$SKIP_PREREQUISITES" == true ]]; then
            print_error "Docker is required but not installed."
            print_info "Install Docker manually or run without --skip-prerequisites"
            exit 1
        else
            install_docker
        fi
    fi
    
    # Check if Docker daemon is running
    if ! docker info &> /dev/null; then
        print_step "Starting Docker daemon..."
        sudo systemctl start docker || {
            print_warning "Could not start Docker daemon automatically."
            print_info "Please start Docker manually: sudo systemctl start docker"
            print_info "Or run with --skip-docker to skip Docker setup"
            if [[ "$SKIP_DOCKER" == false ]]; then
                exit 1
            fi
        }
    fi
}

wait_for_container_health() {
    local container_name=$1
    local max_wait=60
    local count=0
    
    print_step "Waiting for container $container_name to be healthy..."
    
    while [[ $count -lt $max_wait ]]; do
        if docker ps --filter "name=$container_name" --filter "status=running" | grep -q "$container_name"; then
            # Check if container has health check
            health_status=$(docker inspect --format='{{.State.Health.Status}}' "$container_name" 2>/dev/null || echo "no-health-check")
            
            if [[ "$health_status" == "healthy" || "$health_status" == "no-health-check" ]]; then
                print_success "Container $container_name is ready"
                return 0
            elif [[ "$health_status" == "starting" ]]; then
                print_info "Health check starting... ($count/$max_wait)"
            else
                print_info "Health status: $health_status ($count/$max_wait)"
            fi
        else
            print_info "Container not running yet... ($count/$max_wait)"
        fi
        
        sleep 2
        ((count += 2))
    done
    
    print_warning "Container $container_name did not become healthy within ${max_wait}s"
    return 1
}

# ============================================================================
# MAIN INSTALLATION
# ============================================================================

print_header "Price Error Bot Linux Installer"

echo "This installer will:"
echo "  1. Install system prerequisites (Python 3.11+, Git, etc.)"
echo "  2. Install Docker and Docker Compose (if not installed)"
echo "  3. Create Python virtual environment"
echo "  4. Install Python dependencies"
echo "  5. Install Playwright browsers"
echo "  6. Configure environment (.env file)"
echo "  7. Start database containers"
echo "  8. Run database migrations"
echo "  9. Seed default categories"
echo ""

# Check if running as root
check_root

# Detect operating system
print_header "Step 1: System Detection"
detect_os
print_success "Detected OS: $OS $OS_VERSION"

# Install prerequisites
if [[ "$SKIP_PREREQUISITES" == false ]]; then
    print_header "Step 2: Installing Prerequisites"
    install_prerequisites
else
    print_header "Step 2: Skipping Prerequisites (--skip-prerequisites)"
fi

# Find Python
print_header "Step 3: Python Detection"
if ! find_python; then
    print_error "Python 3.11+ is required but not found."
    print_info "Please install Python 3.11+ and try again."
    exit 1
fi

# Docker setup
print_header "Step 4: Docker Setup"
if [[ "$SKIP_DOCKER" == false ]]; then
    check_docker
    print_success "Docker is available"
else
    print_warning "Skipping Docker setup (--skip-docker)"
fi

# Create virtual environment
print_header "Step 5: Python Virtual Environment"
if [[ -d "venv" && "$FORCE" == false ]]; then
    print_success "Virtual environment already exists"
else
    if [[ "$FORCE" == true && -d "venv" ]]; then
        print_step "Removing existing virtual environment..."
        rm -rf venv
    fi
    
    print_step "Creating virtual environment..."
    $PYTHON_CMD -m venv venv
    print_success "Virtual environment created"
fi

# Activate virtual environment
print_step "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
print_header "Step 6: Python Dependencies"
print_step "Upgrading pip..."
python -m pip install --upgrade pip

print_step "Installing project dependencies..."
print_info "This may take a few minutes..."
pip install -e .
print_success "Dependencies installed"

# Install Playwright browsers
print_header "Step 7: Playwright Browser Installation"
print_step "Installing Chromium browser for Playwright..."
playwright install chromium
print_success "Playwright browsers installed"

# Environment configuration
print_header "Step 8: Environment Configuration"
if [[ -f ".env" && "$FORCE" == false ]]; then
    print_success ".env file already exists"
else
    print_step "Creating .env file..."
    
    if [[ -f ".env.example" ]]; then
        cp .env.example .env
        print_success ".env file created from template"
    else
        print_error ".env.example not found! This is a bug."
        exit 1
    fi
    
    # Prompt for Discord webhook
    echo ""
    echo -e "${YELLOW}Would you like to configure a Discord webhook now? (optional)${NC}"
    read -p "Discord Webhook URL (press Enter to skip): " webhook_url
    
    if [[ -n "$webhook_url" ]]; then
        sed -i "s|DISCORD_WEBHOOK_URL=|DISCORD_WEBHOOK_URL=$webhook_url|" .env
        print_success "Discord webhook configured"
    fi
fi

# Start database containers
print_header "Step 9: Database Containers"
if [[ "$SKIP_DOCKER" == false ]]; then
    print_step "Starting PostgreSQL and Redis containers..."
    docker compose up -d postgres redis
    print_success "Database containers started"
    
    # Wait for containers to be healthy
    wait_for_container_health "price_bot_postgres"
    wait_for_container_health "price_bot_redis"
    
    print_success "Database containers are ready"
else
    print_warning "Skipping Docker container startup (--skip-docker flag)"
fi

# Database migrations
print_header "Step 10: Database Migrations"
print_step "Running database migrations..."
alembic upgrade head
print_success "Database migrations completed"

# Seed categories
print_header "Step 11: Seeding Categories"
print_step "Seeding default store categories..."
python scripts/seed_categories.py
print_success "Categories seeded"

# Installation complete
print_header "Installation Complete!"

echo -e "${GREEN}The Price Error Bot has been successfully installed!${NC}"
echo ""
echo -e "${CYAN}To start the bot:${NC}"
echo -e "  ./start.sh"
echo ""
echo -e "${CYAN}Or manually:${NC}"
echo -e "  source venv/bin/activate"
echo -e "  python -c \"import uvicorn; from src.main import app; uvicorn.run(app, host='0.0.0.0', port=8001)\""
echo ""
echo -e "${CYAN}Dashboard URL: http://localhost:8001${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo -e "  1. Start the bot with ./start.sh"
echo -e "  2. Open http://localhost:8001 in your browser"
echo -e "  3. Go to Settings tab to configure Discord webhook"
echo -e "  4. Go to Categories tab to manage store categories"
echo ""

# Offer to start the bot
echo -e "${YELLOW}Would you like to start the bot now? (y/N)${NC}"
read -p "> " start_now
if [[ "$start_now" =~ ^[Yy]$ ]]; then
    echo ""
    ./start.sh
fi