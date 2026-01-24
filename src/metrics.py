"""Prometheus metrics for the Price Error Bot."""

from prometheus_client import Counter, Gauge, Histogram, Info

# Application info
app_info = Info("price_error_bot", "Price Error Bot application info")
app_info.info({"version": "0.1.0", "name": "price-error-bot"})

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
