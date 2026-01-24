# Price Error Bot

Monitor e-commerce prices and detect price errors automatically. Built with Python, FastAPI, and PostgreSQL.

## Features

- **Category-Based Scanning**: Automatically scans deal pages from 15 major retailers
- **Category Discovery**: Automatically discover categories from product URLs - just paste any product link and the bot will find its category
- **Deal Detection**: Detects price errors using configurable discount thresholds
- **Discord Alerts**: Send notifications via Discord webhooks
- **Deduplication**: Avoid spam with intelligent cooldown and dedupe logic
- **Admin UI**: Web-based dashboard for managing categories, rules, and webhooks
- **Price History**: Track price changes over time

### Supported Retailers

**Major Retailers:**
- Amazon
- Walmart
- Target
- Best Buy
- Costco
- Home Depot
- Lowe's

**Electronics & Gaming:**
- Newegg
- Micro Center
- B&H Photo Video
- GameStop

**Department Stores:**
- Macy's
- Kohl's

**Other:**
- Office Depot
- eBay (Buy It Now only)

## Architecture

- **FastAPI** - REST API and admin UI
- **PostgreSQL** - Product and price history storage
- **Redis** - Deduplication cache and rate limiting
- **APScheduler** - Periodic category scanning (every 5 minutes)
- **SQLAlchemy 2.0** - Async ORM
- **Playwright** - Headless browser for JS-rendered pages

## Prerequisites

### System Requirements

- **Operating System**: Windows 10/11, Ubuntu 18.04+, Debian 10+, CentOS 7+, or macOS 10.15+
- **Python**: 3.11 or higher
- **Docker**: Latest stable version
- **Memory**: 4GB RAM minimum, 8GB recommended
- **Storage**: 2GB available space

### Required Software

- **Python 3.11+**: Programming language runtime
- **Docker & Docker Compose**: For database containers
- **Git** (optional): For cloning the repository

## Quick Install (Recommended)

The easiest way to install is using the automated installer. Choose the installer for your operating system:

### Linux/macOS Installation

1. **Clone the repository** (or download and extract the zip file):
   ```bash
   git clone https://github.com/your-repo/price-error-bot.git
   cd price-error-bot
   ```

2. **Run the installer**:
   ```bash
   ./install.sh
   ```

The installer will automatically:
- Install system prerequisites (Python 3.11+, Git, etc.)
- Install Docker and Docker Compose
- Create Python virtual environment
- Install all Python dependencies
- Install Playwright browsers
- Create `.env` configuration file
- Start PostgreSQL and Redis containers
- Run database migrations
- Seed default store categories

#### Linux/macOS Installer Options

```bash
# Skip system package installation
./install.sh --skip-prerequisites

# Skip Docker setup and containers
./install.sh --skip-docker

# Force recreate virtual environment and .env file
./install.sh --force

# Show help
./install.sh --help
```

### Windows Installation

1. **Open PowerShell as Administrator**
2. **Navigate to the project directory**:
   ```powershell
   cd C:\price_error_bot
   ```
3. **Run the installer**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```

The installer will automatically:
- Install Python 3.11+ (via Winget)
- Install Docker Desktop (via Winget)
- Install Git (via Winget)
- Create Python virtual environment
- Install all Python dependencies
- Install Playwright browsers
- Create `.env` configuration file
- Start PostgreSQL and Redis containers
- Run database migrations
- Seed default store categories

#### Windows Installer Options

```powershell
# Skip prerequisite installation (Python, Docker, Git)
.\install.ps1 -SkipPrerequisites

# Skip Docker container checks
.\install.ps1 -SkipDocker

# Force recreate virtual environment and .env file
.\install.ps1 -Force
```

## Manual Installation

If you prefer manual installation or the installer doesn't work:

### Prerequisites

**All Platforms:**
- Python 3.11 or higher
- Docker and Docker Compose
- Git (recommended)

**Platform-Specific:**
- **Windows**: Windows 10 version 1709+ (for Winget), PowerShell 5.1+
- **Linux**: sudo access for package installation
- **macOS**: Homebrew (recommended)

### Step-by-Step Installation

#### 1. Clone the Repository
```bash
git clone <repository-url>
cd price_error_bot
```

#### 2. Create a Virtual Environment

**Linux/macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows:**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

#### 3. Install Dependencies
```bash
pip install -e .
```

#### 4. Install Playwright Browsers
```bash
playwright install chromium
```

#### 5. Configure Environment

Copy the example environment file and edit it:
```bash
cp .env.example .env
```

Edit the `.env` file with your settings. Key variables to configure:

```env
# Database (use defaults for local development)
DATABASE_URL=postgresql+asyncpg://price_bot:localdev@localhost:5432/price_bot

# Redis (use defaults for local development)  
REDIS_URL=redis://localhost:6379/0

# Application settings
APP_HOST=0.0.0.0
APP_PORT=8001
DEBUG=false
LOG_LEVEL=INFO

# Discord webhook (optional - configure via web UI later)
DISCORD_WEBHOOK_URL=

# Other settings have sensible defaults
```

#### 6. Start Database Containers
```bash
docker compose up -d postgres redis
```

Wait for containers to be healthy:
```bash
docker compose ps
```

#### 7. Run Database Migrations
```bash
alembic upgrade head
```

#### 8. Seed Default Categories
```bash
python scripts/seed_categories.py
```

#### 9. Start the Bot

**Linux/macOS:**
```bash
./start.sh
```

**Windows:**
```powershell
.\start.ps1
```

**Or manually:**
```bash
source venv/bin/activate  # Linux/macOS
# .\venv\Scripts\Activate.ps1  # Windows
python -c "import uvicorn; from src.main import app; uvicorn.run(app, host='0.0.0.0', port=8001)"
```

## Starting the Bot

After installation, you have several options to start the bot:

### Option 1: Script Launcher (Recommended)

**Linux/macOS:**
```bash
./start.sh
```

**Windows:**
```powershell
.\start.ps1
```

### Option 2: Desktop Application (Windows Only)
```powershell
.\dist\PriceErrorBot.exe
```
Or double-click `PriceErrorBot.exe` in the `dist` folder.

### Option 3: Python Launcher (Cross-Platform)
```bash
python launcher.py
```

### Option 4: Manual Start
```bash
# Activate virtual environment first
source venv/bin/activate  # Linux/macOS
# .\venv\Scripts\Activate.ps1  # Windows

# Start manually
python -c "import uvicorn; from src.main import app; uvicorn.run(app, host='0.0.0.0', port=8001)"
```

All methods will:
- Check if Docker containers are running (start them if not)
- Check and free port 8001 if in use
- Start the Price Error Bot

**Dashboard URL: http://localhost:8001**

**Note:** The script launcher (start.sh/start.ps1) is recommended for most users as it provides robust startup with health checks and error handling.

## Desktop Application

For a native desktop experience, you can run the bot as a windowed application instead of using a browser. The desktop app combines all functionality from `start.ps1` and `launcher.py` into a single executable.

### Running the Desktop App

**Option 1: Run as Python script**
```powershell
python launcher.py
```

**Option 2: Run as standalone .exe (Recommended)**
```powershell
.\dist\PriceErrorBot.exe
```

Or simply double-click `PriceErrorBot.exe` in the `dist` folder.

The desktop app will:
- Check if Docker Desktop is running
- Start Docker containers if not running
- Check and free port 8001 if in use
- Start the backend server
- Open the dashboard in a native window
- **Show a console window** with live logs (startup progress, errors, and application logs)

### Building a Standalone .exe

You can build a standalone executable that doesn't require Python to be installed:

```powershell
# Build the .exe
.\build_exe.ps1

# The executable will be created at:
# dist\PriceErrorBot.exe
```

Build options:
```powershell
# Clean previous builds before building
.\build_exe.ps1 -Clean

# Skip dependency installation
.\build_exe.ps1 -SkipDeps
```

### Desktop App Features

The `.exe` includes all functionality from both startup methods:
- **Robust port conflict resolution** - Automatically detects and frees port 8001
- **Docker container management** - Checks and starts containers automatically
- **Health verification** - Verifies containers are ready before starting
- **Enhanced error handling** - Clear error messages with actionable suggestions
- **Progress indicators** - Shows startup progress in console
- **Windowed UI** - Native window experience (no browser needed)

### Desktop App Requirements

- **Docker Desktop** must be installed and running (for PostgreSQL and Redis)
- **WebView2 Runtime** (pre-installed on Windows 10/11)

### Console Window and Logs

When you run `PriceErrorBot.exe`, you'll see:
- **Console window** - Shows live logs including:
  - Startup progress (Step 1/4 through Step 4/4)
  - Docker container status
  - Server startup messages
  - Application logs and errors
- **Log files** - All logs are also saved to disk in the `logs/` folder:
  - `logs/app.log` - All application logs (JSON format)
  - `logs/error.log` - Error-level logs only (JSON format)

The console window stays open while the application is running, so you can monitor activity in real-time. Log files are written to the same directory as the `.exe` file.

### Notes

- First launch may take 10-15 seconds while Docker containers and server start
- The .exe file will be approximately 80-120 MB
- All configuration is still done via the web UI or `.env` file
- The .exe can replace both `.\start.ps1` and `python launcher.py` commands
- The console window will always be visible when running the .exe (for monitoring logs)

## Configuration

All configuration is done via the `.env` file or the web dashboard.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://price_bot:localdev@localhost:5432/price_bot` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `DISCORD_WEBHOOK_URL` | Discord webhook for alerts | (empty) |
| `APP_HOST` | Web server host | `0.0.0.0` |
| `APP_PORT` | Web server port | `8001` |
| `DEBUG` | Enable debug mode | `false` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `FETCH_INTERVAL_MINUTES` | Category scan interval | `5` |
| `DEDUPE_TTL_HOURS` | Alert deduplication window | `12` |
| `COOLDOWN_MINUTES` | Per-product alert cooldown | `60` |
| `MAX_CONCURRENT_REQUESTS` | Max concurrent HTTP requests | `10` |
| `REQUESTS_PER_SECOND` | Rate limit | `2.0` |
| `HEADLESS_BROWSER_TIMEOUT` | Browser timeout (seconds) | `30` |

## Usage

1. Access the dashboard at `http://localhost:8001`
2. Go to **Categories** tab to manage store categories
3. Configure Discord webhooks in **Settings**
4. Use **Search Products** tab for advanced product search and filtering
5. The bot will automatically scan categories and send alerts for deals

### Enhanced Search Functionality

The bot includes powerful search capabilities:

**Product Search:**
- Search by product name, SKU, brand, or store
- Use quotes for exact phrases: `"iPhone 13 Pro"`
- Apply filters: price ranges, discounts, stock status
- Sort by relevance, price, discount, or date

**Search Examples:**
```
iphone 13                      # Find iPhone 13 products
"MacBook Pro" store:amazon     # MacBook Pro from Amazon only
sku:B08N5WRWNW                # Find by exact SKU
price:500..1000               # Products priced $500-1000
laptop -refurbished           # Laptops excluding refurbished
```

**Quick Filters:**
- Store selection (Amazon, Walmart, Best Buy, etc.)
- Price ranges with preset options
- Discount percentage minimums
- In-stock only toggle
- Products with active alerts

**Advanced Features:**
- Auto-complete suggestions as you type
- Search result highlighting
- Relevance-based ranking
- Faceted filtering with counts
- Recent search history

### Category Discovery

The bot can automatically discover categories from product URLs. This makes it easy to add new categories without manually finding category URLs.

**How to use:**

1. Go to the **Categories** tab in the dashboard
2. Find the **"Discover Category from Product"** section at the top
3. Paste any product URL from a supported retailer (e.g., `https://www.bestbuy.com/product/...`)
4. Click **"Discover Category"**
5. The bot will extract the category URL and name
6. Click **"Add Category"** to automatically add it for scanning

**Supported retailers for category discovery:**
- Best Buy
- Amazon
- Walmart
- Target
- Newegg
- Micro Center
- Costco
- Home Depot
- Lowe's

**Example:**
```
Product URL: https://www.bestbuy.com/product/ibuypower-y40-gaming-desktop-pc.../J3R75JY7PQ
Discovered: Gaming Desktop Computers
Category URL: https://www.bestbuy.com/site/...
```

The discovered category will be automatically configured with smart defaults:
- Max pages: 5
- Scan interval: 5 minutes
- Priority: 8 (medium-high)

## Troubleshooting

### Installation Issues

#### Python not found or wrong version
**Error:** `python: command not found` or `Python 3.11+ required`

**Solutions:**
- **Linux/macOS**: Install Python 3.11+ using your package manager:
  ```bash
  # Ubuntu/Debian
  sudo apt update && sudo apt install python3.11 python3.11-venv python3.11-dev
  
  # CentOS/RHEL/Fedora
  sudo dnf install python3.11 python3.11-venv python3.11-devel
  
  # macOS (with Homebrew)
  brew install python@3.11
  ```
- **Windows**: Download from https://www.python.org/downloads/
- Check if `python3` command works instead of `python`

#### Virtual environment creation fails
**Error:** `The virtual environment was not created successfully because ensurepip is not available`

**Solutions:**
- **Ubuntu/Debian**: `sudo apt install python3-venv python3-pip`
- **CentOS/RHEL**: `sudo dnf install python3-venv python3-pip`
- **Windows**: Reinstall Python with "Add Python to PATH" checked

#### Docker installation/startup issues
**Error:** `docker: command not found` or `Cannot connect to Docker daemon`

**Solutions:**
1. **Install Docker:**
   - **Linux**: Use the official installer script:
     ```bash
     curl -fsSL https://get.docker.com -o get-docker.sh
     sudo sh get-docker.sh
     sudo usermod -aG docker $USER
     newgrp docker  # Or logout/login
     ```
   - **Windows**: Install Docker Desktop from https://docker.com
   - **macOS**: Install Docker Desktop from https://docker.com

2. **Start Docker daemon:**
   - **Linux**: `sudo systemctl start docker`
   - **Windows/macOS**: Start Docker Desktop application

3. **Fix permissions (Linux):**
   ```bash
   sudo usermod -aG docker $USER
   sudo chmod 666 /var/run/docker.sock
   ```

#### Package installation fails
**Error:** Various pip/package installation errors

**Solutions:**
1. **Update pip:**
   ```bash
   python -m pip install --upgrade pip
   ```

2. **Clear pip cache:**
   ```bash
   pip cache purge
   ```

3. **Install build tools:**
   - **Linux**: `sudo apt install build-essential python3-dev` (Ubuntu/Debian)
   - **Windows**: Install Microsoft Visual C++ Build Tools
   - **macOS**: `xcode-select --install`

### Runtime Issues

#### Port 8001 is in use
**Error:** Port conflict when starting the bot

**Solutions:**
- **Linux/macOS**: The start script automatically handles this, but manually:
  ```bash
  # Find processes using port 8001
  lsof -ti:8001 | xargs kill
  # Or kill all Python processes
  pkill -f python
  ```
- **Windows**: The PowerShell script handles this, but manually:
  ```powershell
  Get-NetTCPConnection -LocalPort 8001 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
  ```

#### Docker containers not starting
**Error:** Database connection failures

**Solutions:**
1. **Check container status:**
   ```bash
   docker compose ps
   docker compose logs postgres
   docker compose logs redis
   ```

2. **Restart containers:**
   ```bash
   docker compose down
   docker compose up -d postgres redis
   ```

3. **Reset Docker environment:**
   ```bash
   docker compose down -v  # WARNING: This deletes data
   docker compose up -d postgres redis
   ```

4. **Check Docker daemon:**
   ```bash
   docker info
   sudo systemctl status docker  # Linux
   ```

#### Database connection errors
**Error:** `connection refused` or `database does not exist`

**Solutions:**
1. **Wait for PostgreSQL to be ready:**
   ```bash
   # Check if container is healthy
   docker inspect price_bot_postgres --format='{{.State.Health.Status}}'
   
   # Wait for startup (can take 30-60 seconds)
   docker compose logs -f postgres
   ```

2. **Check database configuration:**
   - Verify `.env` file has correct `DATABASE_URL`
   - Default: `postgresql+asyncpg://price_bot:localdev@localhost:5432/price_bot`

3. **Recreate database:**
   ```bash
   docker compose down postgres
   docker volume rm price_error_bot_pgdata  # WARNING: Deletes data
   docker compose up -d postgres
   alembic upgrade head
   ```

#### Playwright/browser errors
**Error:** Browser automation fails or Chromium not found

**Solutions:**
1. **Reinstall browsers:**
   ```bash
   playwright install chromium
   playwright install-deps  # Linux only - installs system dependencies
   ```

2. **Check browser installation:**
   ```bash
   playwright install --dry-run chromium
   ```

3. **System dependencies (Linux):**
   ```bash
   # Ubuntu/Debian
   sudo apt install libnss3 libatk-bridge2.0-0 libdrm2 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libxss1 libasound2
   
   # Or use playwright helper
   sudo playwright install-deps chromium
   ```

#### Permission errors
**Error:** Permission denied when starting services

**Solutions:**
1. **Docker permissions (Linux):**
   ```bash
   sudo usermod -aG docker $USER
   newgrp docker
   # Or for immediate effect:
   sudo chmod 666 /var/run/docker.sock
   ```

2. **File permissions:**
   ```bash
   chmod +x install.sh start.sh
   chown -R $USER:$USER .
   ```

#### Module import errors
**Error:** `ModuleNotFoundError` when starting the application

**Solutions:**
1. **Activate virtual environment:**
   ```bash
   source venv/bin/activate  # Linux/macOS
   # .\venv\Scripts\Activate.ps1  # Windows
   ```

2. **Reinstall dependencies:**
   ```bash
   pip install -e .
   ```

3. **Check Python path:**
   ```bash
   which python  # Should point to venv/bin/python
   pip list | grep price-error-bot  # Should show the package
   ```

### Performance Issues

#### High memory usage
**Solutions:**
- Reduce `MAX_CONCURRENT_REQUESTS` in `.env` (default: 10)
- Increase `REQUESTS_PER_SECOND` delay (default: 2.0)
- Monitor with `docker stats`

#### Slow scanning
**Solutions:**
- Check `FETCH_INTERVAL_MINUTES` setting (default: 5 minutes)
- Verify internet connection and retailer accessibility
- Check proxy settings if using proxies

### Search functionality not working

**Error:** Search returns no results or search interface not loading

**Solutions:**
1. **Check database migrations:**
   ```bash
   source venv/bin/activate  # Linux/macOS
   # .\venv\Scripts\Activate.ps1  # Windows
   alembic current
   alembic upgrade head
   ```

2. **Verify search indexes:**
   ```bash
   # Connect to PostgreSQL and verify indexes exist
   docker exec -it price_bot_postgres psql -U price_bot -d price_bot -c "\d+ products"
   
   # Should show indexes including:
   # - idx_products_search_vector (GIN)
   # - idx_products_title_trigram (GIN)
   # - idx_products_sku_trigram (GIN)
   ```

3. **Check PostgreSQL extensions:**
   ```sql
   -- Connect to database and verify extensions
   SELECT * FROM pg_extension WHERE extname IN ('pg_trgm', 'btree_gin');
   ```

4. **Regenerate search vectors:**
   ```sql
   -- If search vectors are empty, regenerate them
   UPDATE products SET search_vector = 
       setweight(to_tsvector('english', COALESCE(title, '')), 'A') ||
       setweight(to_tsvector('english', COALESCE(sku, '')), 'B') ||
       setweight(to_tsvector('english', COALESCE(store, '')), 'C');
   ```

5. **Test with sample data:**
   ```bash
   # Create test data for search functionality
   python scripts/seed_search_data.py
   
   # Verify search API
   curl "http://localhost:8001/api/search/products?q=iphone&limit=5"
   ```

### Getting Help

If you're still experiencing issues:

1. **Check logs:**
   ```bash
   # Application logs
   tail -f logs/app.log
   tail -f logs/error.log
   
   # Docker logs
   docker compose logs postgres redis
   ```

2. **Enable debug mode:**
   - Set `DEBUG=true` in `.env`
   - Set `LOG_LEVEL=DEBUG` in `.env`
   - Restart the application

3. **Verify your setup:**
   - Python version: `python --version`
   - Docker version: `docker --version`
   - Container status: `docker compose ps`
   - Port availability: `netstat -tlnp | grep 8001`

4. **Fresh installation:**
   If all else fails, try a clean installation:
   ```bash
   # Remove everything
   rm -rf venv .env
   docker compose down -v
   
   # Reinstall
   ./install.sh --force
   ```

## Development

### Running Tests
```powershell
pytest
```

### Code Formatting
```powershell
black src tests
ruff check src tests
```

### Database Migrations
```powershell
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

## License

MIT
