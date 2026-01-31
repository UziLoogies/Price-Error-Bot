"""Application configuration using Pydantic settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # Database
    database_url: str = "postgresql+asyncpg://price_bot:localdev@localhost:5432/price_bot"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Discord
    discord_webhook_url: str = ""

    # Keepa API (optional)
    keepa_api_key: str = ""

    # App Settings
    debug: bool = False
    log_level: str = "INFO"
    app_host: str = "0.0.0.0"
    app_port: int = 8001

    # Scheduler
    fetch_interval_minutes: int = 5
    dedupe_ttl_hours: int = 12
    cooldown_minutes: int = 60

    # Rate Limiting
    max_concurrent_requests: int = 10
    requests_per_second: float = 2.0
    
    # ==========================================================================
    # High-Speed Scraping Settings
    # ==========================================================================
    scraper_pool_size: int = 50  # Number of concurrent workers in scraper pool
    http_max_connections: int = 100  # Max connections per domain
    connection_keepalive: int = 20  # Max keepalive connections per domain
    connection_timeout: float = 10.0  # Connection timeout in seconds
    connection_pool_warmup: bool = True  # Pre-warm connections on startup

    # Scan Engine Performance Settings
    max_parallel_category_scans: int = 8  # Number of categories to scan in parallel
    max_parallel_pages_per_category: int = 2  # Number of pages to scan in parallel per category
    min_page_delay_seconds: float = 1.0  # Minimum delay between page requests
    max_page_delay_seconds: float = 3.0  # Maximum delay between page requests
    db_batch_update_size: int = 10  # Number of category updates to batch before committing

    # Session Management
    session_storage_path: str = "data/sessions"
    headless_browser_timeout: int = 30
    category_request_timeout: float = 45.0

    # Retailer-specific rate limits (seconds between requests)
    retailer_rate_limits: dict[str, dict] = {
        "amazon_us": {"min_interval": 30, "max_interval": 60, "jitter": 10},
        "walmart": {"min_interval": 20, "max_interval": 30, "jitter": 5},
        "bestbuy": {"min_interval": 15, "max_interval": 30, "jitter": 5},
        "target": {"min_interval": 20, "max_interval": 30, "jitter": 5},
        "costco": {"min_interval": 45, "max_interval": 60, "jitter": 10},
        "newegg": {"min_interval": 15, "max_interval": 20, "jitter": 3},
    }

    # Low-cost kids item exclusion
    kids_low_price_max: float = 30.0
    kids_exclude_keywords: str = (
        "kid,kids,child,children,toddler,toy,play,playset,pretend,ages,age,"
        "play kitchen,doctor kit,magnetic tiles"
    )
    kids_exclude_skus_walmart: str = (
        "5116478924,780568056,5152678945,10025719060,16501550266"
    )

    # Global deal constraints
    # Minimum retail/original price to consider (prioritize high-ticket items)
    global_min_price: float = 50.0
    global_min_discount_percent: float = 50.0

    # Category scan error handling
    category_disable_on_404: bool = True
    category_error_cooldowns: dict[str, int] = {
        "HTTP 403": 8 * 60 * 60,  # Increased from 6 to 8 hours for persistent failures
        "HTTP 429": 60 * 60,
        "HTTP 500": 30 * 60,
        "HTTP 503": 30 * 60,
        "HTTP 504": 30 * 60,
        "ReadTimeout": 30 * 60,  # Increased from 15 to 30 minutes
        "ReadError": 15 * 60,
        "ConnectError": 30 * 60,  # Added for connection failures
        "Blocked or bot challenge detected": 6 * 60 * 60,
    }

    # ==========================================================================
    # HTTP Caching Settings
    # ==========================================================================
    http_cache_enabled: bool = True
    http_cache_ttl_seconds: int = 300  # 5 minutes
    
    # ==========================================================================
    # Delta Detection Settings
    # ==========================================================================
    delta_detection_enabled: bool = True
    delta_cache_ttl_seconds: int = 3600  # 1 hour
    
    # ==========================================================================
    # Priority-Based Scheduling Settings
    # ==========================================================================
    priority_high_multiplier: float = 1.0    # Priority 8-10: scan at base interval
    priority_medium_multiplier: float = 1.5  # Priority 5-7: 1.5x interval
    priority_low_multiplier: float = 2.0     # Priority 1-4: 2x interval
    success_rate_boost: float = 0.8          # Multiplier for high-yield categories (deals_found >= 5)
    no_deals_penalty: float = 1.25           # Multiplier for categories with no deals
    
    # ==========================================================================
    # Adaptive Rate Limiting Settings
    # ==========================================================================
    adaptive_rate_limiting_enabled: bool = True
    adaptive_base_delay: float = 2.0         # Base delay in seconds
    adaptive_max_delay: float = 30.0         # Maximum delay in seconds
    adaptive_error_rate_threshold: float = 0.3  # Error rate threshold to increase delay
    adaptive_high_latency_ms: float = 5000.0    # Response time threshold for slowdown
    adaptive_429_cooldown_seconds: int = 300    # Time to remain cautious after 429
    
    # ==========================================================================
    # Fallback Fetch Strategy Settings
    # ==========================================================================
    fallback_strategies_enabled: bool = True
    fallback_max_attempts: int = 3           # Maximum strategies to try
    fallback_strategy_order: list[str] = ["static", "static_js_headers", "headless"]
    
    # ==========================================================================
    # Content Analysis Settings
    # ==========================================================================
    content_analysis_enabled: bool = True
    min_expected_products: int = 1           # Minimum products expected on valid page

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
