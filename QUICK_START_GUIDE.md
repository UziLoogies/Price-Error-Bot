# Price Error Bot - Quick Start Guide

> **TL;DR:** Automated bot that scans 15 major retailers every 5 minutes to find pricing errors (40-70%+ discounts) and alerts via Discord.

---

## What It Does

1. **Scans category/deal pages** from Amazon, Best Buy, Walmart, Target, Costco, etc.
2. **Detects pricing errors** using intelligent thresholds (not just any sale)
3. **Filters noise** (kids toys, low-value items, known false positives)
4. **Sends Discord alerts** with product details, images, and discount %

**Example Alert:**
```
💰 Price Drop Alert: MSI Gaming Laptop RTX 4070
Current Price: $799.99
Was: $1,599.99
Drop: 50.0%
🔥 DEAL: 50.0% off (verified by strikethrough, msrp)
```

---

## 5-Minute Setup

### Windows (Recommended)

```powershell
# 1. Clone repository
git clone https://github.com/UziLoogies/Price-Error-Bot
cd Price-Error-Bot

# 2. Run installer (PowerShell as Administrator)
powershell -ExecutionPolicy Bypass -File .\install.ps1

# 3. Start bot
.\start.ps1
# OR double-click: dist\PriceErrorBot.exe

# 4. Open dashboard
# http://localhost:8001
```

**That's it!** The installer handles everything:
- Installs Python, Docker, Git
- Sets up virtual environment
- Configures database
- Seeds default categories

---

## Key Configuration

### 1. Discord Webhook (Optional but Recommended)

**Dashboard:** Settings tab → Add webhook URL

**OR** `.env` file:
```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

### 2. Add Categories to Monitor

**Dashboard:** Categories tab → Add category

**Example Categories:**
- Best Buy Open Box Laptops
- Amazon Lightning Deals (Electronics)
- Walmart Clearance (Gaming)
- Target Daily Deals (Tech)
- Newegg Shell Shocker

### 3. Adjust Thresholds

**Global Filters** (in `.env`):
```env
GLOBAL_MIN_PRICE=50.0              # Ignore items under $50
GLOBAL_MIN_DISCOUNT_PERCENT=50.0   # Only 50%+ discounts
```

**Per-Category Filters** (in dashboard):
- Keywords: "laptop", "gaming", "rtx"
- Exclude: "refurbished", "parts"
- Price range: $500 - $3000
- Minimum discount: 40%

---

## How Detection Works

### Multi-Signal Approach

1. **Strikethrough Price** (Highest confidence)
   - Example: $299 ~~$899~~ = 67% off
   
2. **MSRP Comparison** (Medium confidence)
   - Current price ≤ 50-70% of MSRP
   
3. **Combined Signals** (Enhanced confidence)
   - Strikethrough + MSRP = 90%+ confidence

### Category-Specific Thresholds

```
Electronics:    35%+ off (stricter - errors rare)
Clearance:      40%+ off (already filtered)
Apparel:        55%+ off (sales common)
Open Box:       20%+ off (expected discounts)
```

### Store Adjustments

```
Costco:  Lower thresholds (prices already low)
Macy's:  Higher thresholds (always on sale)
Kohl's:  Higher thresholds (constant sales)
```

---

## Supported Retailers (15)

**Major Retailers:**
- Amazon, Walmart, Target, Best Buy, Costco

**Home Improvement:**
- Home Depot, Lowe's

**Electronics:**
- Newegg, Micro Center, B&H Photo Video

**Gaming:**
- GameStop

**Department Stores:**
- Macy's, Kohl's

**Office:**
- Office Depot

**Marketplace:**
- eBay (Buy It Now only)

---

## Dashboard Overview

**Tabs:**

1. **Dashboard** - Recent activity, scan metrics
2. **Categories** - Manage store categories
3. **Products** - Discovered products and prices
4. **Settings** - Webhooks, global filters
5. **Exclusions** - Filter out false positives
6. **Proxies** - Proxy rotation (optional)

---

## Common Workflows

### Add a New Category

**Method 1: Auto-Discovery**
1. Go to Categories tab
2. Paste any product URL (e.g., Best Buy laptop)
3. Click "Discover Category"
4. Review discovered category and add

**Method 2: Manual**
1. Go to Categories tab → Add Category
2. Select store, enter category name and URL
3. Configure max pages, scan interval, filters
4. Save

### Filter Out Noise

**Add Exclusion:**
1. Exclusions tab → Add Exclusion
2. Choose store
3. Add keyword, brand, or SKU to exclude
4. Enable

**Examples:**
- Keyword: "refurbished", "parts", "case"
- Brand: "Generic", "No Name"
- SKU: "12345678" (specific false positive)

### Tune Detection

**Too many false positives?**
- Increase `min_discount_percent` per category
- Add exclude keywords
- Raise `GLOBAL_MIN_PRICE`

**Missing real deals?**
- Lower `min_discount_percent`
- Check exclusion rules
- Review category thresholds

---

## Environment Variables Cheat Sheet

```env
# Required
DATABASE_URL=postgresql+asyncpg://price_bot:localdev@localhost:5432/price_bot
REDIS_URL=redis://localhost:6379/0

# Application
APP_HOST=0.0.0.0
APP_PORT=8001
LOG_LEVEL=INFO

# Discord (optional)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Scheduler
FETCH_INTERVAL_MINUTES=5      # Scan every 5 min
DEDUPE_TTL_HOURS=12           # Dedupe window
COOLDOWN_MINUTES=60           # Per-product cooldown

# Filters
GLOBAL_MIN_PRICE=50.0         # Min $50
GLOBAL_MIN_DISCOUNT_PERCENT=50.0  # Min 50% off
```

---

## Troubleshooting

### Bot not finding deals?

1. Check scan jobs: Dashboard → Recent Scans
2. Verify categories are enabled
3. Check last scan time
4. Review filters (may be too strict)
5. Check logs: `logs/app.log`

### Getting rate limited / 403 errors?

1. Add proxies: Settings → Proxies
2. Increase scan interval per category
3. Reduce max concurrent scans
4. Check rate limit settings

### Discord alerts not sending?

1. Verify webhook URL in Settings
2. Check webhook is enabled
3. Test webhook: Settings → Test Webhook
4. Review deduplication settings

### Database errors?

```powershell
# Restart containers
docker compose restart postgres redis

# Check container health
docker compose ps

# View logs
docker compose logs postgres
```

---

## Pro Tips

### Best Categories to Monitor

**High-Value Electronics:**
- Best Buy Open Box (laptops, TVs, appliances)
- Amazon Warehouse Deals
- Newegg Shell Shocker
- Micro Center Clearance

**Gaming:**
- Best Buy Gaming Deals
- GameStop Clearance
- Amazon Video Games Deals

**Daily Deals:**
- Amazon Lightning Deals
- Walmart Rollback
- Target Deal of the Day

### Optimal Configuration

```python
Category Priority Guide:
10: Best Buy Open Box Laptops      (scan every 5 min)
9:  Amazon Lightning Deals          (scan every 10 min)
8:  Newegg Shell Shocker            (scan every 10 min)
7:  Walmart Clearance Electronics   (scan every 15 min)
5:  Target Daily Deals              (scan every 30 min)
3:  General clearance               (scan every 60 min)
```

### Reducing False Positives

1. **Set minimum price:** $50+ (filters toys, accessories)
2. **Add exclusions:** "refurbished", "open box", "parts"
3. **Use brand filters:** Whitelist known good brands
4. **Increase discount threshold:** 50%+ for better quality
5. **Review alerts:** Add SKUs to exclusions as needed

### Scaling Up

1. **Add proxies** for aggressive scanning
2. **Increase max parallel scans** (default 3 → 5+)
3. **Add more categories** for broader coverage
4. **Use monitoring** (Grafana) to track performance
5. **Fine-tune thresholds** based on results

---

## Development

### Run Locally

```powershell
# Activate venv
.\venv\Scripts\Activate.ps1

# Start services
docker compose up -d postgres redis

# Run migrations
alembic upgrade head

# Start bot
uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
```

### Add New Retailer

1. Create parser in `src/ingest/category_scanner.py`
2. Register in `CATEGORY_PARSERS`
3. Add rate limits in `src/config.py`
4. Add store adjustments in `src/detect/deal_detector.py`

### Database Migrations

```powershell
# Create migration
alembic revision --autogenerate -m "description"

# Apply migration
alembic upgrade head

# Rollback
alembic downgrade -1
```

---

## Monitoring Stack (Optional)

Start full monitoring suite:

```powershell
docker compose up -d
```

**Access:**
- **Bot Dashboard:** http://localhost:8001
- **Grafana:** http://localhost:3000 (admin/admin)
- **Prometheus:** http://localhost:9090

**Dashboards:**
- Overview: System health, scan rates
- Activity: Recent scans, alerts
- Price History: Product price charts
- Stores: Per-store performance

---

## Next Steps

1. **Initial Setup**
   - [ ] Run installer
   - [ ] Configure Discord webhook
   - [ ] Add 3-5 high-value categories
   - [ ] Test manual scan

2. **Fine-Tuning**
   - [ ] Monitor alerts for 24 hours
   - [ ] Add exclusions for false positives
   - [ ] Adjust category thresholds
   - [ ] Optimize scan intervals

3. **Scale**
   - [ ] Add more categories
   - [ ] Set up proxies if needed
   - [ ] Enable monitoring (Grafana)
   - [ ] Automate startup (Windows Task Scheduler)

4. **Maintain**
   - [ ] Check weekly for parser failures
   - [ ] Update category URLs as needed
   - [ ] Review and clean exclusions
   - [ ] Monitor Discord alert quality

---

## Resources

- **Full Documentation:** `ANALYSIS_SUMMARY.md`
- **Logs:** `logs/app.log`, `logs/error.log`
- **Dashboard:** http://localhost:8001
- **GitHub:** https://github.com/UziLoogies/Price-Error-Bot

---

## FAQ

**Q: How often does it scan?**  
A: Every 5 minutes by default, configurable per category.

**Q: Does it track individual products?**  
A: No, it's category-based. Discovers products from category pages.

**Q: Can I add my own categories?**  
A: Yes! Use category discovery or manual entry.

**Q: Why am I getting too many alerts?**  
A: Increase min discount %, add exclusions, raise min price.

**Q: Can I run multiple instances?**  
A: Not recommended. Use more categories instead.

**Q: Does it work on Linux/Mac?**  
A: Yes, but installer is Windows-only. Follow manual setup.

**Q: Is it legal?**  
A: Web scraping is legal for public data. Be respectful with rate limits.

**Q: Can I sell the deals?**  
A: You can share alerts, but purchases are up to individuals.

---

**Happy deal hunting! 🎉**
