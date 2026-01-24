# Price Error Bot - Repository Analysis Summary

**Analysis Date:** January 24, 2026  
**Repository:** https://github.com/UziLoogies/Price-Error-Bot  
**Branch:** cursor/price-error-bot-analysis-b4d1

---

## Executive Summary

The Price Error Bot is a sophisticated Python-based monitoring system that automatically discovers and alerts on price errors across 15 major e-commerce retailers. It uses category-based scanning (not individual product tracking) to find significant discounts in near real-time.

**Key Capabilities:**
- Scans deal/category pages from retailers every 5 minutes
- Detects price errors using intelligent discount thresholds (40-70%+ off)
- Sends Discord webhook alerts for significant deals
- Supports 15+ retailers with custom parsers for each
- Filters out noise (kids items, low-value products, exclusions)
- Desktop application with embedded web UI

---

## Architecture Overview

### Technology Stack

```
Backend:
- FastAPI (REST API + Web UI)
- PostgreSQL (product storage, price history)
- Redis (deduplication, rate limiting)
- SQLAlchemy 2.0 (async ORM)
- APScheduler (periodic scanning)

Scraping:
- httpx (HTTP client with proxy support)
- Selectolax (fast HTML parsing)
- Playwright (headless browser for JS-rendered pages)
- Custom category parsers for each retailer

Desktop App:
- PyWebView (native windowed UI)
- PyInstaller (standalone .exe)
- Integrated Docker container management

Monitoring (Optional):
- Prometheus (metrics)
- Grafana (dashboards)
- Loki + Promtail (log aggregation)
```

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Price Error Bot                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   FastAPI    │    │  Scheduler   │    │   Desktop    │  │
│  │   Web UI     │◄───┤ APScheduler  │◄───┤   Launcher   │  │
│  │  (Dashboard) │    │  (5 min)     │    │  (PyWebView) │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────────┘  │
│         │                   │                                │
│         ▼                   ▼                                │
│  ┌────────────────────────────────────────┐                 │
│  │         Scan Engine (Parallel)         │                 │
│  │  - Max 3 concurrent category scans     │                 │
│  │  - Smart scheduling by priority        │                 │
│  │  - Progress tracking                   │                 │
│  └────────────────┬───────────────────────┘                 │
│                   │                                          │
│                   ▼                                          │
│  ┌─────────────────────────────────────────────────┐        │
│  │        Category Scanner (15 retailers)          │        │
│  │  - Store-specific HTML parsers                  │        │
│  │  - Proxy rotation                               │        │
│  │  - Rate limiting (retailer-specific)            │        │
│  │  - Bot detection handling                       │        │
│  └────────────────┬────────────────────────────────┘        │
│                   │                                          │
│                   ▼                                          │
│  ┌─────────────────────────────────────────────────┐        │
│  │          Deal Detector Engine                   │        │
│  │  - Category-specific thresholds                 │        │
│  │  - Store adjustments                            │        │
│  │  - Multi-signal confidence scoring              │        │
│  │  - Strikethrough + MSRP comparison              │        │
│  └────────────────┬────────────────────────────────┘        │
│                   │                                          │
│                   ▼                                          │
│  ┌─────────────────────────────────────────────────┐        │
│  │             Filter Pipeline                     │        │
│  │  - Global exclusions (kids items, brands)       │        │
│  │  - Category-specific filters (keywords, price)  │        │
│  │  - Minimum price ($50+) and discount (50%+)     │        │
│  └────────────────┬────────────────────────────────┘        │
│                   │                                          │
│                   ▼                                          │
│  ┌─────────────────────────────────────────────────┐        │
│  │        Notification System                      │        │
│  │  - Discord webhooks                             │        │
│  │  - Deduplication (12hr TTL)                     │        │
│  │  - Cooldown per product (60min)                 │        │
│  │  - Grafana annotations (optional)               │        │
│  └─────────────────────────────────────────────────┘        │
│                                                               │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   ┌──────────┐        ┌──────────┐        ┌──────────┐
   │PostgreSQL│        │  Redis   │        │ Discord  │
   │ Products │        │ Dedupe   │        │ Webhook  │
   │  Prices  │        │RateLimit │        │  Alerts  │
   └──────────┘        └──────────┘        └──────────┘
```

---

## Core Components

### 1. Category Scanner (`src/ingest/category_scanner.py`)

**Purpose:** Scrapes category/deal pages from retailers to discover products

**Supported Retailers (15):**
1. Amazon (US)
2. Walmart
3. Best Buy
4. Target
5. Costco
6. Home Depot
7. Lowe's
8. Newegg
9. Micro Center
10. GameStop
11. B&H Photo Video
12. Macy's
13. Kohl's
14. Office Depot
15. eBay (Buy It Now only)

**Key Features:**
- Store-specific HTML parsers using CSS selectors
- Extracts: SKU, title, current price, original price, MSRP, image URL
- Multi-page scanning (configurable max pages per category)
- Proxy rotation support
- Retailer-specific rate limiting
- Bot detection and retry logic (403, 503 handling)
- User-agent rotation

**Example Category:**
```python
{
    "store": "bestbuy",
    "category_name": "Open Box Laptops",
    "category_url": "https://www.bestbuy.com/site/open-box/laptops",
    "max_pages": 5,
    "enabled": True
}
```

### 2. Deal Detector (`src/detect/deal_detector.py`)

**Purpose:** Identifies price errors without requiring prior price history

**Detection Methods:**

1. **Strikethrough Comparison** (Highest confidence)
   - Compares current price to displayed "was" price
   - Example: $299 (was $899) = 67% off

2. **MSRP Comparison** (Medium confidence)
   - Compares to manufacturer's suggested retail price
   - Threshold: Price ≤ 50-70% of MSRP

3. **Combined Signals** (Enhanced confidence)
   - Multiple indicators = higher confidence
   - Strikethrough + MSRP = 90%+ confidence

**Category-Specific Thresholds:**

```python
CATEGORY_THRESHOLDS = {
    "electronics": {
        "min_discount_percent": 35.0,    # Stricter
        "msrp_threshold": 0.65,           # Must be ≤65% of MSRP
        "min_price": 25.0,
        "max_price": 5000.0
    },
    "clearance": {
        "min_discount_percent": 40.0,    # Already filtered
        "msrp_threshold": 0.60,
        "min_price": 5.0,
        "max_price": 10000.0
    },
    "apparel": {
        "min_discount_percent": 55.0,    # More generous
        "msrp_threshold": 0.45,           # Sales common
        "min_price": 10.0,
        "max_price": 1000.0
    }
}
```

**Store Adjustments:**

```python
STORE_ADJUSTMENTS = {
    "costco": {"min_discount_multiplier": 0.75},      # Already low prices
    "macys": {"min_discount_multiplier": 1.15},       # Always on sale
    "kohls": {"min_discount_multiplier": 1.10}        # Constant sales
}
```

**Confidence Scoring:**
- Base: 0.5
- +0.2 for reasonable discount (50-70%)
- +0.15 for strikethrough price available
- +0.10 for MSRP available
- +0.15 bonus for multiple signals
- Result: 0.1 - 1.0 scale

### 3. Scan Engine (`src/ingest/scan_engine.py`)

**Purpose:** Orchestrates parallel scanning with progress tracking

**Features:**
- Parallel scanning (max 3 concurrent categories)
- Smart scheduling based on:
  - Category priority (1-10)
  - Last scan time
  - Scan interval per category
- Progress tracking with callbacks
- Filter pipeline integration
- Database persistence

**Workflow:**
```python
1. Load enabled categories (sorted by priority)
2. Filter categories due for scanning
3. Create scan job record
4. Scan categories in parallel (semaphore limit)
5. Apply filters (keywords, price, exclusions)
6. Detect deals
7. Update category stats
8. Process discovered deals
```

### 4. Filter System (`src/ingest/filters.py`)

**Purpose:** Removes noise and low-value items

**Global Filters:**
- Minimum price: $50+
- Minimum discount: 50%+
- Kids items under $30 (excludes toys, play sets)
- Specific SKU exclusions (known false positives)

**Category Filters:**
- Required keywords (e.g., "laptop", "gaming")
- Excluded keywords (e.g., "refurbished", "parts")
- Brand whitelist/blacklist
- Price range (min/max)

**Example:**
```python
FilterConfig(
    keywords=["laptop", "gaming", "desktop"],
    exclude_keywords=["refurbished", "open box", "parts"],
    brands=["ASUS", "MSI", "Alienware"],
    min_price=500.0,
    max_price=3000.0
)
```

### 5. Notification System

**Discord Webhooks (`src/notify/discord.py`):**
- Formatted embeds with product details
- Price drop percentage
- Product image
- Confidence indicator
- Color-coded (green = high confidence, orange = medium)

**Deduplication (`src/notify/dedupe.py`):**
- 12-hour deduplication window (Redis TTL)
- 60-minute cooldown per product
- Prevents spam for same deal

**Grafana Annotations (Optional):**
- Timeline visualization
- Alert correlation
- Best-effort delivery

### 6. Worker/Scheduler (`src/worker/`)

**Scheduled Jobs:**

1. **Category Scan** (Every 5 minutes)
   - Scans all enabled categories
   - Smart filtering based on interval
   - Parallel execution

2. **Baseline Recalculation** (Daily at 3 AM)
   - Updates 30-day average prices
   - For any discovered products

**Task Runner:**
- Processes discovered deals
- Adds products to database
- Sends Discord alerts
- Updates scan metrics

---

## Database Schema

### Core Tables

**products**
- id, sku, store, url, title, image_url
- msrp, baseline_price
- created_at

**price_history**
- id, product_id, price, original_price
- shipping, availability, confidence
- fetched_at

**store_categories**
- id, store, category_name, category_url
- enabled, max_pages, scan_interval_minutes, priority
- keywords, exclude_keywords, brands (JSON)
- min_price, max_price, min_discount_percent
- last_scanned, products_found, deals_found
- last_error, last_error_at

**product_exclusions**
- id, store, sku, keyword, brand
- reason, enabled, created_at

**webhooks**
- id, name, url, enabled

**proxy_configs**
- id, name, host, port, username, password
- enabled, last_used, failure_count

**scan_jobs**
- id, job_type, status, started_at, completed_at
- total_items, processed_items, success_count, error_count
- products_found, deals_found

---

## Setup and Installation

### Prerequisites
- Windows 10+ (for .exe installer)
- Python 3.11+
- Docker Desktop
- Git (optional)

### Automated Installation (Recommended)

```powershell
# One-click install (PowerShell as Administrator)
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

**Installer Actions:**
1. Installs Python 3.11+ (via Winget)
2. Installs Docker Desktop (via Winget)
3. Installs Git (via Winget)
4. Creates Python virtual environment
5. Installs dependencies from pyproject.toml
6. Installs Playwright Chromium browser
7. Creates .env configuration file
8. Starts PostgreSQL + Redis containers
9. Runs database migrations (Alembic)
10. Seeds default store categories

### Manual Installation

```powershell
# 1. Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -e .

# 3. Install Playwright browsers
playwright install chromium

# 4. Create .env file (see Environment Variables section)

# 5. Start Docker containers
docker compose up -d postgres redis

# 6. Run migrations
alembic upgrade head

# 7. Seed categories
python scripts/seed_categories.py

# 8. Start bot
.\start.ps1
# OR
python launcher.py
# OR
.\dist\PriceErrorBot.exe
```

---

## Environment Variables

### Required Configuration

**Database:**
- `DATABASE_URL` - PostgreSQL connection string
  - Default: `postgresql+asyncpg://price_bot:localdev@localhost:5432/price_bot`

**Redis:**
- `REDIS_URL` - Redis connection string
  - Default: `redis://localhost:6379/0`

**Application:**
- `APP_HOST` - Web server host (default: `0.0.0.0`)
- `APP_PORT` - Web server port (default: `8001`)
- `DEBUG` - Debug mode (default: `false`)
- `LOG_LEVEL` - Logging level (default: `INFO`)

### Optional Configuration

**Discord:**
- `DISCORD_WEBHOOK_URL` - Discord webhook URL for alerts
  - Can also be configured via web UI Settings tab

**Keepa API:**
- `KEEPA_API_KEY` - Keepa API key for Amazon data (optional)

**Scheduler:**
- `FETCH_INTERVAL_MINUTES` - Category scan interval (default: `5`)
- `DEDUPE_TTL_HOURS` - Alert deduplication window (default: `12`)
- `COOLDOWN_MINUTES` - Per-product alert cooldown (default: `60`)

**Rate Limiting:**
- `MAX_CONCURRENT_REQUESTS` - Max concurrent HTTP requests (default: `10`)
- `REQUESTS_PER_SECOND` - Global rate limit (default: `2.0`)

**Browser:**
- `HEADLESS_BROWSER_TIMEOUT` - Playwright timeout in seconds (default: `30`)

**Filters:**
- `GLOBAL_MIN_PRICE` - Global minimum price filter (default: `50.0`)
- `GLOBAL_MIN_DISCOUNT_PERCENT` - Global minimum discount (default: `50.0`)
- `KIDS_LOW_PRICE_MAX` - Max price for kids item exclusion (default: `30.0`)

### Example .env File

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

# Discord Webhook
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN

# Scheduler Settings
FETCH_INTERVAL_MINUTES=5
DEDUPE_TTL_HOURS=12
COOLDOWN_MINUTES=60

# Rate Limiting
MAX_CONCURRENT_REQUESTS=10
REQUESTS_PER_SECOND=2.0

# Filtering
GLOBAL_MIN_PRICE=50.0
GLOBAL_MIN_DISCOUNT_PERCENT=50.0
```

---

## Dependencies

### Core Python Packages (from pyproject.toml)

**Web Framework:**
- fastapi>=0.109.0
- uvicorn[standard]>=0.27.0
- jinja2>=3.1.3
- python-multipart>=0.0.6

**Database:**
- sqlalchemy>=2.0.23
- alembic>=1.13.0
- asyncpg>=0.29.0
- psycopg2-binary>=2.9.9

**Caching/Queue:**
- redis>=5.0.1

**Scraping:**
- httpx>=0.26.0
- playwright>=1.40.0
- beautifulsoup4>=4.12.0
- selectolax>=0.3.17

**Scheduling:**
- apscheduler>=3.10.4

**Configuration:**
- pydantic>=2.5.0
- pydantic-settings>=2.1.0
- python-dotenv>=1.0.0

**Monitoring:**
- prometheus-fastapi-instrumentator>=6.1.0
- prometheus-client>=0.19.0
- python-json-logger>=2.0.7

**Desktop App:**
- pywebview>=4.4.1
- psutil>=5.9.0

**Build (Optional):**
- pyinstaller>=6.0.0 (for .exe build)

**Development (Optional):**
- pytest>=7.4.4
- pytest-asyncio>=0.23.3
- black>=24.1.1
- ruff>=0.1.11

### Docker Services (from docker-compose.yml)

**Required:**
- PostgreSQL 16 Alpine
- Redis 7 Alpine

**Optional (Monitoring):**
- Prometheus v2.48.0
- Grafana 10.2.0
- Loki 2.9.0
- Promtail 2.9.0

---

## How Price Error Detection Works

### Detection Flow

```
1. CATEGORY SCANNING
   ├─ Fetch category page HTML
   ├─ Parse product cards (SKU, title, prices, images)
   ├─ Extract current_price, original_price, msrp
   └─ Return list of DiscoveredProduct objects

2. FILTERING
   ├─ Apply global exclusions (kids items, brands, SKUs)
   ├─ Apply category filters (keywords, price range)
   ├─ Enforce minimum price ($50+)
   └─ Return filtered products

3. DEAL DETECTION
   ├─ For each product:
   │  ├─ Check strikethrough discount
   │  ├─ Check MSRP ratio
   │  ├─ Calculate confidence score
   │  └─ Apply category/store thresholds
   ├─ Filter to significant deals (40%+ off, 0.6+ confidence)
   └─ Return DetectedDeal objects

4. PROCESSING
   ├─ Check if product already in database
   ├─ Add new products with initial price history
   ├─ Check deduplication (Redis)
   └─ Send Discord alert if significant

5. NOTIFICATION
   ├─ Format Discord embed
   ├─ Include product details, image, discount
   ├─ Send to enabled webhooks
   └─ Push Grafana annotation (optional)
```

### Example Detection

**Product Found:**
```python
DiscoveredProduct(
    sku="6534615",
    store="bestbuy",
    title="MSI Katana 15 Gaming Laptop - RTX 4070",
    url="https://www.bestbuy.com/site/...",
    current_price=Decimal("799.99"),
    original_price=Decimal("1599.99"),  # Strikethrough price
    msrp=Decimal("1699.99"),
    image_url="https://..."
)
```

**Deal Detection:**
```python
1. Strikethrough discount: (1599.99 - 799.99) / 1599.99 = 50%
2. MSRP ratio: 799.99 / 1699.99 = 0.47 (≤ 0.70 threshold)
3. Confidence: 0.5 + 0.2 (50% discount) + 0.15 (strikethrough) + 0.10 (msrp) = 0.95
4. Multiple signals: YES → boost confidence to 1.0

DetectedDeal(
    product=product,
    discount_percent=50.0,
    detection_method="combined",
    confidence=1.0,
    reason="50.0% off (verified by strikethrough, msrp)",
    is_significant=True,
    is_price_error=False  # Not extreme enough
)
```

**Discord Alert:**
```
💰 Price Drop Alert: MSI Katana 15 Gaming Laptop - RTX 4070

Current Price: $799.99
Was: $1,599.99
Drop: 50.0%
Reason: 🔥 DEAL: 50.0% off (verified by strikethrough, msrp)

SKU: 6534615 | bestbuy
[Product Image]
```

### Detection Signals Priority

1. **Strikethrough Price** (Confidence +0.15)
   - Most reliable signal
   - Directly from retailer
   - Example: "was $899" crossed out

2. **MSRP Comparison** (Confidence +0.10)
   - Second most reliable
   - Manufacturer suggested price
   - Sometimes inflated

3. **Discount Percentage** (Confidence +0.2 for 50-70%)
   - Combined with above signals
   - Category/store adjusted

4. **Multiple Signals** (Confidence +0.15)
   - Strikethrough + MSRP = very high confidence
   - Reduces false positives

---

## Key Features and Workflows

### 1. Category Discovery

**Purpose:** Auto-discover categories from product URLs

**Workflow:**
1. User pastes any product URL (e.g., Best Buy laptop)
2. System extracts category from breadcrumbs/URL
3. Finds category page URL
4. Adds category to database with smart defaults
5. Begins scanning on next scheduled run

**Supported Stores:**
- Best Buy, Amazon, Walmart, Target, Newegg, Micro Center, Costco, Home Depot, Lowe's

### 2. Smart Scheduling

**Priority-Based Scanning:**
- Categories have priority 1-10
- Higher priority scanned first
- Scan interval per category (default 30 min)
- Only scan if interval elapsed

**Example:**
```python
Priority 10: Best Buy Open Box Laptops (every 5 min)
Priority 8:  Amazon Lightning Deals (every 10 min)
Priority 5:  Walmart Clearance (every 30 min)
Priority 2:  Target Toys (every 60 min)
```

### 3. Proxy Rotation

**Purpose:** Avoid IP bans and rate limits

**Features:**
- Store proxy configurations in database
- Round-robin rotation
- Failure tracking and auto-disable
- Per-proxy success/failure metrics

**Configuration:**
```python
ProxyConfig(
    name="Proxy 1",
    host="proxy.example.com",
    port=8080,
    username="user",
    password="pass",
    enabled=True
)
```

### 4. Product Exclusions

**Purpose:** Filter out noise and false positives

**Types:**
1. **Global Exclusions**
   - Kids items under $30
   - Known false positive SKUs
   - Generic spam keywords

2. **Category Exclusions**
   - Per-category keyword filters
   - Brand filters
   - Price ranges

3. **Manual Exclusions**
   - User-added SKUs
   - Specific brands/keywords
   - Store-specific

**Example:**
```python
ProductExclusion(
    store="walmart",
    keyword="refurbished",
    reason="Too many false positives",
    enabled=True
)
```

### 5. Desktop Application

**Features:**
- Native windowed UI (PyWebView)
- Embedded browser (no Chrome/Firefox needed)
- Auto-manages Docker containers
- Port conflict resolution
- Live console logs
- Single .exe (80-120 MB)

**Build:**
```powershell
.\build_exe.ps1
# Creates: dist\PriceErrorBot.exe
```

---

## API Endpoints

### Web UI (Dashboard)
- `GET /` - Main dashboard (HTML)

### Categories
- `GET /api/categories` - List all categories
- `POST /api/categories` - Add category
- `PUT /api/categories/{id}` - Update category
- `DELETE /api/categories/{id}` - Delete category
- `POST /api/categories/{id}/scan` - Trigger manual scan
- `POST /api/categories/discover` - Discover from product URL

### Products
- `GET /api/products` - List products
- `GET /api/products/{id}` - Get product details
- `GET /api/products/{id}/history` - Price history

### Webhooks
- `GET /api/webhooks` - List webhooks
- `POST /api/webhooks` - Add webhook
- `PUT /api/webhooks/{id}` - Update webhook
- `DELETE /api/webhooks/{id}` - Delete webhook

### Proxies
- `GET /api/proxies` - List proxies
- `POST /api/proxies` - Add proxy
- `PUT /api/proxies/{id}` - Update proxy
- `DELETE /api/proxies/{id}` - Delete proxy

### Exclusions
- `GET /api/exclusions` - List exclusions
- `POST /api/exclusions` - Add exclusion
- `DELETE /api/exclusions/{id}` - Delete exclusion

### Scans
- `GET /api/scans/recent` - Recent scan activity
- `GET /api/scans/jobs` - Scan job history
- `POST /api/scans/manual` - Trigger manual scan

### Stores
- `GET /api/stores` - List supported stores

---

## Monitoring and Observability

### Prometheus Metrics
- Request latency/throughput
- Database query performance
- Scan job metrics
- Deal detection rates
- Alert delivery success

### Grafana Dashboards
- **Overview:** System health, scan rates, deal discovery
- **Activity:** Recent scans, alerts, errors
- **Price History:** Product price charts
- **Stores:** Per-store performance
- **Alerts:** Alert timeline and volume

### Logs
- JSON formatted logs
- Structured logging with python-json-logger
- Log levels: DEBUG, INFO, WARNING, ERROR
- Promtail → Loki → Grafana (optional)
- Files: `logs/app.log`, `logs/error.log`

---

## Troubleshooting

### Common Issues

**1. Port 8001 in use**
```powershell
# Auto-handled by start.ps1, or manually:
Get-NetTCPConnection -LocalPort 8001 | ForEach-Object { 
    Stop-Process -Id $_.OwningProcess -Force 
}
```

**2. Docker containers not starting**
```powershell
# Ensure Docker Desktop is running
docker compose up -d postgres redis

# Check health
docker compose ps
```

**3. Database connection errors**
```powershell
# Wait for PostgreSQL to be healthy
docker inspect price_bot_postgres --format='{{.State.Health.Status}}'

# Should show: healthy
```

**4. Playwright browser errors**
```powershell
# Reinstall browsers
playwright install chromium
```

**5. 403 Forbidden / Bot Detection**
- Enable proxy rotation
- Increase rate limit intervals
- Reduce concurrent scans
- Check user-agent rotation

**6. No products found**
- Verify category URL is correct
- Check if store changed their HTML structure
- Review logs for parser errors
- Try manual scan from dashboard

**7. No deals detected**
- Lower `min_discount_percent` threshold
- Check global filters (min price, etc.)
- Verify category thresholds
- Review exclusion rules

---

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

**Create Migration:**
```powershell
alembic revision --autogenerate -m "description"
```

**Apply Migrations:**
```powershell
alembic upgrade head
```

**Rollback:**
```powershell
alembic downgrade -1
```

### Adding a New Retailer

1. Create parser in `src/ingest/category_scanner.py`:
```python
class NewStoreCategoryParser(BaseCategoryParser):
    store_name = "newstore"
    base_url = "https://www.newstore.com"
    
    def parse_category_page(self, html: str, category_url: str) -> List[DiscoveredProduct]:
        # Parse products from HTML
        pass
```

2. Register in `CATEGORY_PARSERS`:
```python
CATEGORY_PARSERS = {
    "newstore": NewStoreCategoryParser(),
}
```

3. Add rate limits in `src/config.py`:
```python
retailer_rate_limits = {
    "newstore": {"min_interval": 20, "max_interval": 30, "jitter": 5},
}
```

4. Add store adjustments in `src/detect/deal_detector.py`:
```python
STORE_ADJUSTMENTS = {
    "newstore": {"min_discount_multiplier": 0.90},
}
```

---

## Recommended Next Steps

### 1. Initial Setup
- [ ] Run installer: `.\install.ps1`
- [ ] Configure Discord webhook in Settings tab
- [ ] Add initial categories for monitoring
- [ ] Test manual scan to verify functionality

### 2. Optimization
- [ ] Fine-tune category thresholds based on results
- [ ] Add product exclusions for known false positives
- [ ] Configure proxy rotation if getting rate limited
- [ ] Adjust scan intervals based on category activity

### 3. Expansion
- [ ] Add more high-value categories (laptops, GPUs, TVs)
- [ ] Create store-specific category lists
- [ ] Implement category discovery from deal forums
- [ ] Add more retailers if needed

### 4. Monitoring
- [ ] Set up Grafana dashboards (optional)
- [ ] Monitor alert quality and adjust filters
- [ ] Track false positive rate
- [ ] Review scan job history for errors

### 5. Maintenance
- [ ] Regularly update category URLs if changed
- [ ] Monitor for HTML parser failures
- [ ] Update rate limits based on retailer tolerance
- [ ] Clean up old scan jobs and price history

---

## Technical Highlights

### Strengths

1. **Category-First Architecture**
   - No need to pre-populate products
   - Automatically discovers new deals
   - Scales horizontally (more categories = more coverage)

2. **Intelligent Detection**
   - Multi-signal confidence scoring
   - Category-aware thresholds
   - Store-specific adjustments
   - False positive reduction

3. **Robust Scraping**
   - Retailer-specific parsers
   - Proxy rotation
   - Rate limiting
   - Bot detection handling
   - Retry logic with exponential backoff

4. **Production Ready**
   - Docker containerization
   - Database migrations (Alembic)
   - Monitoring (Prometheus + Grafana)
   - Structured logging
   - Error tracking

5. **User-Friendly**
   - Desktop application (no CLI needed)
   - Web dashboard
   - Category discovery from URLs
   - Discord integration

### Areas for Improvement

1. **Parser Maintenance**
   - HTML selectors break when stores redesign
   - Need regular updates
   - Consider more robust parsing (machine learning?)

2. **Rate Limiting**
   - Could be more sophisticated
   - Per-IP tracking
   - Adaptive based on response codes

3. **Scalability**
   - Currently single-instance
   - Could benefit from distributed workers
   - Redis-based job queue for horizontal scaling

4. **Detection Accuracy**
   - Some false positives still occur
   - Could use historical data for validation
   - Machine learning for price error prediction

5. **Testing**
   - Limited test coverage
   - Need more integration tests
   - Mock retailer responses for CI/CD

---

## Security and Privacy

### API Keys/Secrets
- Discord webhooks (sensitive)
- Keepa API key (if used)
- Database credentials
- Proxy credentials

**Storage:** `.env` file (gitignored)

### Data Collection
- Product metadata (SKU, title, URL)
- Price snapshots
- No personal user data
- No login credentials for retailers

### Rate Limiting
- Respectful scraping intervals
- Retailer-specific limits
- Proxy rotation to distribute load
- Exponential backoff on failures

---

## License

MIT License (per README.md)

---

## Conclusion

The Price Error Bot is a well-architected, production-ready system for discovering retail pricing errors. It combines intelligent detection algorithms, robust scraping infrastructure, and user-friendly interfaces to deliver real-time deal alerts.

**Best Use Cases:**
- Finding pricing mistakes on major retailers
- Monitoring clearance/open-box sections
- Deal hunting for high-value electronics
- Automated deal aggregation for Discord communities

**Key Success Factors:**
- Maintain category URLs (stores change them)
- Fine-tune thresholds to reduce noise
- Use proxies for aggressive scanning
- Monitor and update HTML parsers regularly

The system is particularly effective for electronics, gaming, and computing categories where pricing errors can represent significant savings ($100-$1000+).
