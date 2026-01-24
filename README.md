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

## Quick Install (Recommended)

The easiest way to install is using the automated installer. It will install all prerequisites and set up the application.

### One-Click Installation

1. Open PowerShell as Administrator
2. Navigate to the project directory:
   ```powershell
   cd C:\price_error_bot
   ```
3. Run the installer:
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

### Installer Options

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

- Windows 10 version 1709 or later (for Winget)
- Python 3.11+
- Docker Desktop
- Git (optional)

### Step-by-Step Installation

1. **Clone the repository**
   ```powershell
   git clone <repository-url>
   cd price_error_bot
   ```

2. **Create a virtual environment**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install dependencies**
   ```powershell
   pip install -e .
   ```

4. **Install Playwright browsers**
   ```powershell
   playwright install chromium
   ```

5. **Create `.env` file** with the following content:
   ```env
   # Database
   DATABASE_URL=postgresql+asyncpg://price_bot:localdev@localhost:5432/price_bot

   # Redis
   REDIS_URL=redis://localhost:6379/0

   # Application
   APP_HOST=0.0.0.0
   APP_PORT=8001
   DEBUG=false
   LOG_LEVEL=INFO

   # Discord Webhook (optional)
   DISCORD_WEBHOOK_URL=
   ```

6. **Start database containers**
   ```powershell
   docker compose up -d postgres redis
   ```

7. **Run database migrations**
   ```powershell
   alembic upgrade head
   ```

8. **Seed default categories**
   ```powershell
   python scripts/seed_categories.py
   ```

9. **Start the bot**
   ```powershell
   .\start.ps1
   ```

## Starting the Bot

After installation, you have three options to start the bot:

### Option 1: Desktop Application (Recommended)
```powershell
.\dist\PriceErrorBot.exe
```
Or double-click `PriceErrorBot.exe` in the `dist` folder.

### Option 2: PowerShell Script
```powershell
.\start.ps1
```

### Option 3: Python Launcher
```powershell
python launcher.py
```

All methods will:
- Check if Docker containers are running (start them if not)
- Check and free port 8001 if in use
- Start the Price Error Bot

Dashboard URL: **http://localhost:8001**

**Note:** The desktop application (`.exe`) is recommended as it combines all functionality and provides the best user experience.

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
4. The bot will automatically scan categories and send alerts for deals

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

### Port 8001 is in use
The `start.ps1` script automatically kills processes using port 8001. If it fails:
```powershell
Get-NetTCPConnection -LocalPort 8001 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### Docker containers not starting
Make sure Docker Desktop is running:
```powershell
docker compose up -d postgres redis
```

### Database connection errors
Wait for PostgreSQL to be healthy:
```powershell
docker compose ps
```

### Playwright browser errors
Reinstall Playwright browsers:
```powershell
playwright install chromium
```

### Winget not available
Winget requires Windows 10 version 1709 or later. Install from Microsoft Store:
https://apps.microsoft.com/store/detail/app-installer/9NBLGGH4NNS1

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
