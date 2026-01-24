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

    # Session Management
    session_storage_path: str = "data/sessions"
    headless_browser_timeout: int = 30

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
    global_min_price: float = 50.0
    global_min_discount_percent: float = 50.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
