"""SQLAlchemy database models."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Product(Base):
    """Product to monitor."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    store: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Product image URL
    msrp: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    msrp_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # keepa, manual, etc.
    msrp_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    baseline_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )  # When we first discovered this product
    price_change_count_24h: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_price_change_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    price_history: Mapped[list["PriceHistory"]] = relationship(
        "PriceHistory", back_populates="product", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        "Alert", back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("sku", "store", name="uq_product_sku_store"),)


class PriceHistory(Base):
    """Price history for products."""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    original_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )  # Strikethrough/was price
    shipping: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )
    availability: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float] = mapped_column(default=1.0, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="price_history")


class Rule(Base):
    """Detection rule configuration."""

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    alerts: Mapped[list["Alert"]] = relationship(
        "Alert", back_populates="rule", cascade="all, delete-orphan"
    )


class Alert(Base):
    """Alerts sent for price errors."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False
    )
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("rules.id"), nullable=False)
    triggered_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    previous_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    discord_message_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    false_positive_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="alerts")
    rule: Mapped["Rule"] = relationship("Rule", back_populates="alerts")


class Webhook(Base):
    """Webhook configuration for multi-platform notifications."""

    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Webhook type: discord, telegram, slack, generic
    webhook_type: Mapped[str] = mapped_column(String(32), default="discord", nullable=False)
    
    # Custom message template (Jinja2 format)
    template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Custom headers for generic webhooks (JSON string)
    headers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Filters for which alerts to send (JSON string)
    # Format: {"min_discount": 50, "stores": ["amazon_us"], "categories": ["electronics"]}
    filters: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Telegram-specific fields
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    telegram_bot_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    
    # Statistics
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    send_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class ProxyConfig(Base):
    """Proxy configuration for rotating proxies (datacenter, residential, ISP)."""

    __tablename__ = "proxy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    host: Mapped[str] = mapped_column(String(256), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Proxy type classification
    proxy_type: Mapped[str] = mapped_column(
        String(32), default="datacenter", nullable=False
    )  # 'datacenter', 'residential', 'isp'
    provider: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # US, EU, etc.
    cost_per_gb: Mapped[Optional[float]] = mapped_column(nullable=True)  # For residential proxies
    
    # Health tracking
    success_rate: Mapped[float] = mapped_column(default=1.0, nullable=False)
    avg_latency_ms: Mapped[float] = mapped_column(default=0.0, nullable=False)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_success: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class StoreCategory(Base):
    """Store category configuration for category scanning."""

    __tablename__ = "store_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store: Mapped[str] = mapped_column(String(32), nullable=False)
    category_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category_url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_scanned: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    products_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deals_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Scan configuration
    max_pages: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    scan_interval_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1-10

    # Filtering configuration (stored as JSON strings)
    keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    exclude_keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    brands: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    min_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    max_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)

    # Deal detection thresholds (override global defaults)
    min_discount_percent: Mapped[Optional[float]] = mapped_column(nullable=True)
    msrp_threshold: Mapped[Optional[float]] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("store", "category_url", name="uq_store_category_url"),
    )


class ScanJob(Base):
    """Tracks scan job progress and results."""

    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 'category', 'product', 'manual'
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending, running, completed, failed
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Progress tracking
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Results
    products_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deals_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Context
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("store_categories.id"), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.total_items == 0:
            return 0.0
        return (self.processed_items / self.total_items) * 100


class ProductExclusion(Base):
    """Exclusion list for products to skip during scanning."""

    __tablename__ = "product_exclusions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store: Mapped[str] = mapped_column(String(32), nullable=False)
    sku: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Specific product
    keyword: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)  # Keyword pattern
    brand: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # Brand to exclude
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class ProductBaselineCache(Base):
    """Cached price baseline calculations for products.
    
    Stores pre-computed baseline statistics to avoid recalculating
    on every price check. Updated periodically by baseline job.
    """

    __tablename__ = "product_baseline_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=False, unique=True
    )
    
    # Rolling averages
    avg_price_7d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    avg_price_30d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    
    # Price range
    min_price_seen: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_price_seen: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    
    # Current baseline (best estimate of "normal" price)
    current_baseline: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    
    # Statistics
    price_stability: Mapped[float] = mapped_column(default=0.5, nullable=False)  # 0.0-1.0
    std_deviation: Mapped[Optional[float]] = mapped_column(nullable=True)
    observation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Timestamps
    last_calculated: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    last_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    last_price_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationship
    product: Mapped["Product"] = relationship("Product")


class NotificationHistory(Base):
    """History of notifications sent for tracking and debugging."""

    __tablename__ = "notification_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    webhook_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("webhooks.id"), nullable=False
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=True
    )
    
    # Notification details
    notification_type: Mapped[str] = mapped_column(String(32), nullable=False)  # alert, test, etc.
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # sent, failed, pending
    
    # Content
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON payload sent
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Response from webhook
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timing
    sent_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)