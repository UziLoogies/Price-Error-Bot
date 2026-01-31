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

# Error trend metrics
http_errors_total = Counter(
    "http_errors_total",
    "Total HTTP errors by status code",
    ["store", "status_code"],  # 403, 404, 503, etc.
)

# Proxy health metrics
proxy_403_failures_total = Counter(
    "proxy_403_failures_total",
    "Total 403 failures per proxy",
    ["proxy_id"],
)

proxy_consecutive_403s = Gauge(
    "proxy_consecutive_403s",
    "Current consecutive 403 failures for proxy",
    ["proxy_id"],
)

proxy_cooldown_active = Gauge(
    "proxy_cooldown_active",
    "Whether proxy is in cooldown (1 = yes, 0 = no)",
    ["proxy_id"],
)

# Selector failure metrics
selector_failures_total = Counter(
    "selector_failures_total",
    "Total selector failures (0 products parsed)",
    ["store", "reason"],  # stale_selector, js_rendered, unknown
)

headless_fallback_attempts = Counter(
    "headless_fallback_attempts_total",
    "Total headless browser fallback attempts",
    ["store", "success"],  # success = true/false
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

# Encryption/Decryption metrics
decryption_failures_total = Counter(
    "decryption_failures_total",
    "Total number of decryption failures",
    ["exception_type"],
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


# =============================================================================
# Error Trend Helper Functions
# =============================================================================

def record_http_error(store: str, status_code: int):
    """Record an HTTP error by status code."""
    http_errors_total.labels(store=store, status_code=str(status_code)).inc()


# =============================================================================
# Proxy Health Helper Functions
# =============================================================================

def record_proxy_403_failure(proxy_id: int):
    """Record a 403 failure for a proxy."""
    proxy_403_failures_total.labels(proxy_id=str(proxy_id)).inc()


def update_proxy_consecutive_403s(proxy_id: int, count: int):
    """Update consecutive 403 failures for a proxy."""
    proxy_consecutive_403s.labels(proxy_id=str(proxy_id)).set(count)


def update_proxy_cooldown(proxy_id: int, in_cooldown: bool):
    """Update proxy cooldown status."""
    proxy_cooldown_active.labels(proxy_id=str(proxy_id)).set(1 if in_cooldown else 0)


# =============================================================================
# Selector Failure Helper Functions
# =============================================================================

def record_selector_failure(store: str, reason: str):
    """Record a selector failure (0 products parsed)."""
    selector_failures_total.labels(store=store, reason=reason).inc()


def record_headless_fallback(store: str, success: bool):
    """Record a headless browser fallback attempt."""
    headless_fallback_attempts.labels(store=store, success="true" if success else "false").inc()


# =============================================================================
# Encryption/Decryption Helper Functions
# =============================================================================

def record_decryption_failure(exception_type: str):
    """Record a decryption failure."""
    decryption_failures_total.labels(exception_type=exception_type).inc()


# =============================================================================
# AI/LLM Metrics
# =============================================================================

# Embedding metrics
embedding_generation_latency = Histogram(
    "embedding_generation_latency_seconds",
    "Time to generate embeddings",
    ["model_name"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0],
)

embedding_generation_total = Counter(
    "embedding_generation_total",
    "Total number of embeddings generated",
    ["model_name", "batch"],
)

embedding_cache_hits = Counter(
    "embedding_cache_hits_total",
    "Embedding cache hits",
)

embedding_cache_misses = Counter(
    "embedding_cache_misses_total",
    "Embedding cache misses",
)

# LLM metrics
llm_calls_total = Counter(
    "llm_calls_total",
    "Total number of LLM API calls",
    ["model_name", "task_type"],  # task_type: anomaly_review, attribute_extraction, etc.
)

llm_call_latency = Histogram(
    "llm_call_latency_seconds",
    "LLM API call latency",
    ["model_name", "task_type"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

llm_cost_usd = Counter(
    "llm_cost_usd_total",
    "Total LLM API cost in USD",
    ["model_name"],
)

llm_cache_hits = Counter(
    "llm_cache_hits_total",
    "LLM cache hits",
    ["model_name"],
)

llm_cache_misses = Counter(
    "llm_cache_misses_total",
    "LLM cache misses",
    ["model_name"],
)

llm_errors_total = Counter(
    "llm_errors_total",
    "Total LLM API errors",
    ["model_name", "error_type"],
)

# Product matching metrics
product_matching_attempts = Counter(
    "product_matching_attempts_total",
    "Total product matching attempts",
)

product_matches_found = Counter(
    "product_matches_found_total",
    "Total product matches found",
    ["similarity_tier"],  # 0.85-0.9, 0.9-0.95, 0.95+
)

product_matching_latency = Histogram(
    "product_matching_latency_seconds",
    "Product matching query latency",
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0],
)

# Attribute extraction metrics
attribute_extraction_attempts = Counter(
    "attribute_extraction_attempts_total",
    "Total attribute extraction attempts",
    ["method"],  # ner, rule, llm
)

attribute_extraction_success = Counter(
    "attribute_extraction_success_total",
    "Successful attribute extractions",
    ["method", "attribute_type"],  # attribute_type: brand, model, size, etc.
)

attribute_extraction_latency = Histogram(
    "attribute_extraction_latency_seconds",
    "Attribute extraction latency",
    ["method"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0],
)


# =============================================================================
# AI/LLM Helper Functions
# =============================================================================

def record_embedding_generation(model_name: str, latency: float, batch_size: int = 1):
    """Record embedding generation."""
    embedding_generation_latency.labels(model_name=model_name).observe(latency)
    embedding_generation_total.labels(model_name=model_name, batch=str(batch_size > 1)).inc(batch_size)


def record_embedding_cache_hit():
    """Record an embedding cache hit."""
    embedding_cache_hits.inc()


def record_embedding_cache_miss():
    """Record an embedding cache miss."""
    embedding_cache_misses.inc()


def record_llm_call(model_name: str, task_type: str, latency: float, cost: float = 0.0):
    """Record an LLM API call."""
    llm_calls_total.labels(model_name=model_name, task_type=task_type).inc()
    llm_call_latency.labels(model_name=model_name, task_type=task_type).observe(latency)
    if cost > 0:
        llm_cost_usd.labels(model_name=model_name).inc(cost)


def record_llm_cache_hit(model_name: str):
    """Record an LLM cache hit."""
    llm_cache_hits.labels(model_name=model_name).inc()


def record_llm_cache_miss(model_name: str):
    """Record an LLM cache miss."""
    llm_cache_misses.labels(model_name=model_name).inc()


def record_llm_error(model_name: str, error_type: str):
    """Record an LLM API error."""
    llm_errors_total.labels(model_name=model_name, error_type=error_type).inc()


def record_product_matching(latency: float, matches_found: int, similarity_scores: list[float]):
    """Record product matching results."""
    product_matching_attempts.inc()
    product_matching_latency.observe(latency)
    
    for score in similarity_scores:
        if score >= 0.95:
            tier = "0.95+"
        elif score >= 0.9:
            tier = "0.9-0.95"
        elif score >= 0.85:
            tier = "0.85-0.9"
        else:
            tier = "<0.85"
        product_matches_found.labels(similarity_tier=tier).inc()


def record_attribute_extraction(method: str, latency: float, success: bool, attributes_found: list[str] = None):
    """Record attribute extraction attempt."""
    attribute_extraction_attempts.labels(method=method).inc()
    attribute_extraction_latency.labels(method=method).observe(latency)
    
    if success and attributes_found:
        for attr_type in attributes_found:
            attribute_extraction_success.labels(method=method, attribute_type=attr_type).inc()
