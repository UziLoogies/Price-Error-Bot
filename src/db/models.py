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
from sqlalchemy.dialects.postgresql import TSVECTOR, JSONB
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
    baseline_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    search_vector: Mapped[Optional[str]] = mapped_column(TSVECTOR, nullable=True)

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

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="alerts")
    rule: Mapped["Rule"] = relationship("Rule", back_populates="alerts")


class Webhook(Base):
    """Discord webhook configuration."""

    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ProxyConfig(Base):
    """Proxy configuration for rotating datacenter proxies."""

    __tablename__ = "proxy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    host: Mapped[str] = mapped_column(String(256), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    search_vector: Mapped[Optional[str]] = mapped_column(TSVECTOR, nullable=True)

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


class SearchQuery(Base):
    """Search query analytics and logging."""

    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    filters: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class SearchSuggestion(Base):
    """Search suggestions and autocomplete data."""

    __tablename__ = "search_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    suggestion_text: Mapped[str] = mapped_column(String(256), nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_used: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("entity_type", "field_name", "suggestion_text", name="uq_search_suggestions"),
    )
