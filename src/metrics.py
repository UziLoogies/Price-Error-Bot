"""Prometheus metrics for the Price Error Bot."""

from prometheus_client import Counter, Gauge, Histogram, Info

# Application info
app_info = Info("price_error_bot", "Price Error Bot application info")
app_info.info({"version": "0.1.0", "name": "price-error-bot"})

# =============================================================================
# Category Scan Metrics
# =============================================================================

category_scan_duration = Histogram(
    "category_scan_duration_seconds",
    "Time to scan a category",
    ["store", "category"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

products_discovered = Counter(
    "products_discovered_total",
    "Products discovered from category scans",
    ["store"],
)

deals_detected = Counter(
    "deals_detected_total",
    "Deals detected from scans",
    ["store", "discount_tier"],  # 50-60%, 60-70%, 70%+
)

scan_blocks = Counter(
    "scan_blocks_total",
    "Times scanning was blocked",
    ["store", "block_type"],  # captcha, 403, 429, cloudflare
)

active_scans = Gauge(
    "active_category_scans",
    "Currently running category scans",
)

# =============================================================================
# Caching Metrics
# =============================================================================

cache_hits = Counter(
    "http_cache_hits_total",
    "HTTP cache hits (304 responses)",
    ["store"],
)

cache_misses = Counter(
    "http_cache_misses_total",
    "HTTP cache misses (new content fetched)",
    ["store"],
)

# =============================================================================
# Delta Detection Metrics
# =============================================================================

delta_skips = Counter(
    "delta_skip_total",
    "Products skipped due to no change",
    ["store"],
)

delta_changes = Counter(
    "delta_change_total",
    "Products detected with changes",
    ["store"],
)

# =============================================================================
# Store Health Metrics
# =============================================================================

store_response_time = Histogram(
    "store_response_time_ms",
    "Response time for store requests in milliseconds",
    ["store"],
    buckets=[100, 250, 500, 1000, 2000, 5000, 10000, 30000],
)

store_error_rate = Gauge(
    "store_error_rate",
    "Current error rate for store (0.0 - 1.0)",
    ["store"],
)

store_consecutive_failures = Gauge(
    "store_consecutive_failures",
    "Number of consecutive failures for store",
    ["store"],
)

adaptive_delay_seconds = Gauge(
    "adaptive_delay_seconds",
    "Current adaptive delay for store",
    ["store"],
)

# =============================================================================
# Performance Metrics (Enhanced)
# =============================================================================

scraping_latency = Histogram(
    "scraping_latency_ms",
    "Latency for page scraping in milliseconds",
    ["domain"],
    buckets=[50, 100, 250, 500, 1000, 2000, 5000, 10000],
)

proxy_success_rate = Gauge(
    "proxy_success_rate",
    "Success rate for proxy (0.0 - 1.0)",
    ["proxy_id", "proxy_type"],
)

connection_pool_utilization = Gauge(
    "connection_pool_utilization",
    "Connection pool utilization (0.0 - 1.0)",
    ["domain"],
)

cache_hit_rate = Gauge(
    "cache_hit_rate",
    "Cache hit rate (0.0 - 1.0)",
    ["store"],
)

pages_scanned_per_second = Gauge(
    "pages_scanned_per_second",
    "Pages scanned per second",
)

concurrent_requests = Gauge(
    "concurrent_requests",
    "Number of concurrent HTTP requests",
)

scraper_pool_queue_size = Gauge(
    "scraper_pool_queue_size",
    "Number of tasks in scraper pool queue",
)

scraper_pool_active_workers = Gauge(
    "scraper_pool_active_workers",
    "Number of active workers in scraper pool",
)

proxy_avg_latency = Histogram(
    "proxy_avg_latency_ms",
    "Average latency for proxy in milliseconds",
    ["proxy_id", "proxy_type"],
    buckets=[100, 250, 500, 1000, 2000, 5000, 10000],
)

residential_proxy_cost = Gauge(
    "residential_proxy_cost_usd",
    "Monthly cost for residential proxies in USD",
)

# =============================================================================
# Fetch Strategy Metrics
# =============================================================================

fetch_strategy_attempts = Counter(
    "fetch_strategy_attempts_total",
    "Fetch strategy attempts",
    ["store", "strategy"],
)

fetch_strategy_success = Counter(
    "fetch_strategy_success_total",
    "Successful fetch strategy attempts",
    ["store", "strategy"],
)

fetch_strategy_fallback = Counter(
    "fetch_strategy_fallback_total",
    "Times fallback strategy was needed",
    ["store", "from_strategy", "to_strategy"],
)

# Fetch metrics
price_fetches_total = Counter(
    "price_fetches_total",
    "Total number of price fetch attempts",
    ["store", "status"],
)

price_fetch_errors_total = Counter(
    "price_fetch_errors_total",
    "Total number of failed price fetches",
    ["store", "error_type"],
)

price_fetch_duration_seconds = Histogram(
    "price_fetch_duration_seconds",
    "Time spent fetching prices",
    ["store"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

# Alert metrics
price_alerts_total = Counter(
    "price_alerts_total",
    "Total number of price alerts triggered",
    ["store", "rule_type"],
)

alerts_sent_total = Counter(
    "alerts_sent_total",
    "Total number of alerts sent to Discord",
    ["store", "status"],
)

# Product metrics
products_monitored = Gauge(
    "products_monitored",
    "Number of products currently being monitored",
    ["store"],
)

# Price change metrics
price_changes_total = Counter(
    "price_changes_total",
    "Total number of price changes detected",
    ["store", "direction"],
)

# Current price tracking (sampled for high-value items)
current_price_gauge = Gauge(
    "current_price_dollars",
    "Current price of monitored products",
    ["store", "sku"],
)

# Scheduler metrics
scheduler_runs_total = Counter(
    "scheduler_runs_total",
    "Total number of scheduler runs",
    ["job_type", "status"],
)

scheduler_last_run_timestamp = Gauge(
    "scheduler_last_run_timestamp",
    "Timestamp of last scheduler run",
    ["job_type"],
)

# Database metrics
db_queries_total = Counter(
    "db_queries_total",
    "Total number of database queries",
    ["operation"],
)

# Webhook metrics
webhook_requests_total = Counter(
    "webhook_requests_total",
    "Total number of webhook requests",
    ["status"],
)

webhook_latency_seconds = Histogram(
    "webhook_latency_seconds",
    "Webhook request latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)


def update_products_monitored(store_counts: dict[str, int]):
    """Update the products_monitored gauge with current counts."""
    for store, count in store_counts.items():
        products_monitored.labels(store=store).set(count)


def record_fetch_success(store: str, duration: float):
    """Record a successful price fetch."""
    price_fetches_total.labels(store=store, status="success").inc()
    price_fetch_duration_seconds.labels(store=store).observe(duration)


def record_fetch_error(store: str, error_type: str, duration: float):
    """Record a failed price fetch."""
    price_fetches_total.labels(store=store, status="error").inc()
    price_fetch_errors_total.labels(store=store, error_type=error_type).inc()
    price_fetch_duration_seconds.labels(store=store).observe(duration)


def record_price_change(store: str, old_price: float, new_price: float):
    """Record a price change."""
    direction = "up" if new_price > old_price else "down"
    price_changes_total.labels(store=store, direction=direction).inc()


def record_alert_triggered(store: str, rule_type: str):
    """Record an alert being triggered."""
    price_alerts_total.labels(store=store, rule_type=rule_type).inc()


def record_alert_sent(store: str, success: bool):
    """Record an alert being sent to Discord."""
    status = "success" if success else "error"
    alerts_sent_total.labels(store=store, status=status).inc()


def record_scheduler_run(job_type: str, success: bool):
    """Record a scheduler job run."""
    import time
    status = "success" if success else "error"
    scheduler_runs_total.labels(job_type=job_type, status=status).inc()
    scheduler_last_run_timestamp.labels(job_type=job_type).set(time.time())


# =============================================================================
# Category Scan Helper Functions
# =============================================================================

def record_category_scan(store: str, category: str, duration: float, products: int, deals: int):
    """Record a category scan completion."""
    category_scan_duration.labels(store=store, category=category).observe(duration)
    products_discovered.labels(store=store).inc(products)
    
    # Categorize deals by discount tier
    # Note: deals count is passed in, tier categorization happens at detection time


def record_deal_detected(store: str, discount_percent: float):
    """Record a deal detection with discount tier."""
    if discount_percent >= 70:
        tier = "70%+"
    elif discount_percent >= 60:
        tier = "60-70%"
    else:
        tier = "50-60%"
    deals_detected.labels(store=store, discount_tier=tier).inc()


def record_scan_block(store: str, block_type: str):
    """Record a scan being blocked."""
    scan_blocks.labels(store=store, block_type=block_type).inc()


def increment_active_scans():
    """Increment the active scans gauge."""
    active_scans.inc()


def decrement_active_scans():
    """Decrement the active scans gauge."""
    active_scans.dec()


# =============================================================================
# Caching Helper Functions
# =============================================================================

def record_cache_hit(store: str):
    """Record an HTTP cache hit (304 response)."""
    cache_hits.labels(store=store).inc()


def record_cache_miss(store: str):
    """Record an HTTP cache miss."""
    cache_misses.labels(store=store).inc()


# =============================================================================
# Delta Detection Helper Functions
# =============================================================================

def record_delta_skip(store: str, count: int = 1):
    """Record products skipped due to no change."""
    delta_skips.labels(store=store).inc(count)


def record_delta_change(store: str, count: int = 1):
    """Record products detected with changes."""
    delta_changes.labels(store=store).inc(count)


# =============================================================================
# Store Health Helper Functions
# =============================================================================

def record_store_response(store: str, duration_ms: float, success: bool):
    """Record a store response for health tracking."""
    store_response_time.labels(store=store).observe(duration_ms)


def update_store_health(store: str, error_rate: float, consecutive_failures: int, delay: float):
    """Update store health metrics."""
    store_error_rate.labels(store=store).set(error_rate)
    store_consecutive_failures.labels(store=store).set(consecutive_failures)
    adaptive_delay_seconds.labels(store=store).set(delay)


# =============================================================================
# Fetch Strategy Helper Functions
# =============================================================================

def record_fetch_strategy_attempt(store: str, strategy: str):
    """Record a fetch strategy attempt."""
    fetch_strategy_attempts.labels(store=store, strategy=strategy).inc()


def record_fetch_strategy_success(store: str, strategy: str):
    """Record a successful fetch strategy."""
    fetch_strategy_success.labels(store=store, strategy=strategy).inc()


def record_fetch_fallback(store: str, from_strategy: str, to_strategy: str):
    """Record a fallback to another strategy."""
    fetch_strategy_fallback.labels(
        store=store, from_strategy=from_strategy, to_strategy=to_strategy
    ).inc()
