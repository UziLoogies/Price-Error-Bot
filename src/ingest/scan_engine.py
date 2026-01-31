"""Enhanced scan engine with parallel scanning and progress tracking."""

import asyncio
import logging
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import StoreCategory, ScanJob, ProductExclusion
from src.db.session import AsyncSessionLocal
from src.ingest.category_scanner import CategoryScanner, DiscoveredProduct
from src.ingest.delta_detector import delta_detector
from src.ingest.store_health import store_health
from src.ingest.filters import (
    FilterConfig,
    ProductFilter,
    exclusion_manager,
    filter_low_cost_kids_items,
    is_low_cost_kids_item,
)
from src.config import settings
from src.detect.deal_detector import deal_detector, DetectedDeal
from src import metrics

logger = logging.getLogger(__name__)


def _get_error_cooldown_seconds(error_message: Optional[str]) -> Optional[int]:
    if not error_message:
        return None
    message = error_message.lower()
    for key, seconds in settings.category_error_cooldowns.items():
        if key.lower() in message:
            return seconds
    return None


@dataclass
class ScanResult:
    """Result of a category scan."""
    
    category_id: int
    category_name: str
    store: str
    products_found: int
    deals_found: int
    products: List[DiscoveredProduct] = field(default_factory=list)
    deals: List[DetectedDeal] = field(default_factory=list)
    error: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class ScanProgress:
    """Tracks progress of a scan job."""
    
    job_id: int
    total_categories: int
    completed_categories: int = 0
    total_products: int = 0
    total_deals: int = 0
    errors: List[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)
    results: List[ScanResult] = field(default_factory=list)
    
    @property
    def progress_percent(self) -> float:
        if self.total_categories == 0:
            return 0.0
        return (self.completed_categories / self.total_categories) * 100
    
    @property
    def is_complete(self) -> bool:
        return self.completed_categories >= self.total_categories


class ScanEngine:
    """Enhanced scan engine with parallel scanning and progress tracking."""
    
    def __init__(
        self,
        max_parallel_scans: Optional[int] = None,
        scanner: Optional[CategoryScanner] = None,
    ):
        # Use configurable setting with fallback to default
        self.max_parallel_scans = (
            max_parallel_scans 
            or settings.max_parallel_category_scans
        )
        self.scanner = scanner or CategoryScanner()
        
        # Active scans tracking
        self._active_jobs: Dict[int, ScanProgress] = {}
        self._progress_callbacks: List[Callable] = []
    
    def register_progress_callback(self, callback: Callable[[ScanProgress], None]):
        """Register a callback to be called when scan progress updates."""
        self._progress_callbacks.append(callback)
    
    def _notify_progress(self, progress: ScanProgress):
        """Notify all registered callbacks of progress update."""
        for callback in self._progress_callbacks:
            try:
                callback(progress)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")
    
    async def create_scan_job(
        self,
        db: AsyncSession,
        job_type: str,
        category_id: Optional[int] = None,
        total_items: int = 0,
    ) -> ScanJob:
        """Create a new scan job record."""
        job = ScanJob(
            job_type=job_type,
            status="pending",
            category_id=category_id,
            total_items=total_items,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job
    
    async def update_scan_job(
        self,
        db: AsyncSession,
        job_id: int,
        **kwargs
    ):
        """Update a scan job with new values."""
        job = await db.get(ScanJob, job_id)
        if job:
            for key, value in kwargs.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            await db.commit()
    
    def _build_category_url(self, category: Dict[str, Any]) -> str:
        """Build full category URL from category dict."""
        category_url = category["category_url"]
        store = category["store"]
        
        if not category_url.startswith("http"):
            base_urls = {
                "amazon_us": "https://www.amazon.com",
                "walmart": "https://www.walmart.com",
                "bestbuy": "https://www.bestbuy.com",
                "target": "https://www.target.com",
                "costco": "https://www.costco.com",
                "macys": "https://www.macys.com",
                "homedepot": "https://www.homedepot.com",
                "lowes": "https://www.lowes.com",
            }
            category_url = base_urls.get(store, "") + category_url
        
        return category_url
    
    def _get_retail_price(self, product: DiscoveredProduct) -> Optional[Decimal]:
        """Get retail price from product, checking original_price, msrp, then current_price."""
        if product.original_price is not None:
            return product.original_price
        if product.msrp is not None:
            return product.msrp
        if product.current_price is not None:
            return product.current_price
        return None
    
    def _should_include_product(
        self,
        product: DiscoveredProduct,
        product_filter: Optional[ProductFilter],
        min_retail: Optional[Decimal],
    ) -> bool:
        """Check if product should be included after applying all filters."""
        # Apply category-specific filters
        if product_filter and not product_filter.should_include(product):
            return False
        
        # Check global exclusions
        if exclusion_manager.is_excluded(product):
            return False
        
        # Filter low-cost kids items
        if is_low_cost_kids_item(product):
            return False
        
        # Enforce global minimum retail/original price
        if min_retail:
            retail_price = self._get_retail_price(product)
            if retail_price is None or retail_price < min_retail:
                return False
        
        return True
    
    def _filter_products(
        self,
        products: List[DiscoveredProduct],
        filter_config: Optional[FilterConfig],
    ) -> List[DiscoveredProduct]:
        """Filter products using all configured filters."""
        min_retail = None
        if getattr(settings, "global_min_price", 0) and settings.global_min_price > 0:
            min_retail = Decimal(str(settings.global_min_price))
        
        product_filter = ProductFilter(filter_config) if filter_config else None
        
        filtered_products = []
        for product in products:
            if self._should_include_product(product, product_filter, min_retail):
                filtered_products.append(product)
        
        return filtered_products
    
    async def _filter_products_with_delta(
        self,
        products: List[DiscoveredProduct],
        filter_config: Optional[FilterConfig],
        store: str,
    ) -> List[DiscoveredProduct]:
        """
        Filter products using all configured filters plus delta detection.
        
        Delta detection skips products that haven't changed since last scan.
        
        Args:
            products: List of discovered products
            filter_config: Optional filter configuration
            store: Store identifier for delta detection
            
        Returns:
            Filtered list of products
        """
        # Apply standard filters first
        filtered = self._filter_products(products, filter_config)
        
        # Apply delta detection
        if settings.delta_detection_enabled:
            filtered = await delta_detector.filter_changed(filtered, store)
        
        return filtered
    
    def _detect_significant_deals(
        self,
        products: List[DiscoveredProduct],
        category: Dict[str, Any],
    ) -> List[DetectedDeal]:
        """Detect and filter significant deals from products."""
        min_discount = category.get("min_discount_percent", 50.0)
        if getattr(settings, "global_min_discount_percent", 0) and settings.global_min_discount_percent > 0:
            min_discount = max(min_discount, settings.global_min_discount_percent)
        
        deals = deal_detector.detect_deals_batch(products, min_confidence=0.5)
        return [d for d in deals if d.discount_percent >= min_discount]
    
    async def scan_category(
        self,
        category: Dict[str, Any],
        filter_config: Optional[FilterConfig] = None,
    ) -> ScanResult:
        """
        Scan a single category and return results.
        
        Args:
            category: Category data dict
            filter_config: Optional filter configuration
            
        Returns:
            ScanResult with products and deals found
        """
        start_time = datetime.utcnow()
        store = category.get("store", "Unknown")
        category_name = category.get("category_name", "Unknown")
        
        # Track active scans
        metrics.increment_active_scans()
        
        try:
            category_url = self._build_category_url(category)
            max_pages = category.get("max_pages", 5)
            
            # Scan the category
            products = await self.scanner.scan_category(
                store=store,
                category_url=category_url,
                max_pages=max_pages,
            )
            
            # Record discovered products metric
            if products:
                metrics.products_discovered.labels(store=store).inc(len(products))
            
            # Filter products with delta detection
            products = await self._filter_products_with_delta(products, filter_config, store)
            
            # Detect deals
            significant_deals = self._detect_significant_deals(products, category)
            
            # Record deal metrics by tier
            for deal in significant_deals:
                metrics.record_deal_detected(store, deal.discount_percent)
            
            # Mark products as seen for delta detection
            if products and settings.delta_detection_enabled:
                await delta_detector.mark_seen(products, store)
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            # Record category scan duration metric
            metrics.record_category_scan(
                store=store,
                category=category_name,
                duration=duration,
                products=len(products),
                deals=len(significant_deals),
            )
            
            return ScanResult(
                category_id=category["id"],
                category_name=category_name,
                store=store,
                products_found=len(products),
                deals_found=len(significant_deals),
                products=products,
                deals=significant_deals,
                duration_seconds=duration,
            )
            
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"Scan failed for category {category_name}: {e}")
            
            # Record error metrics
            error_type = "unknown"
            error_str = str(e).lower()
            if "403" in error_str:
                error_type = "403"
            elif "429" in error_str:
                error_type = "429"
            elif "captcha" in error_str or "blocked" in error_str:
                error_type = "blocked"
            elif "timeout" in error_str:
                error_type = "timeout"
            
            metrics.record_scan_block(store, error_type)
            
            return ScanResult(
                category_id=category["id"],
                category_name=category_name,
                store=store,
                products_found=0,
                deals_found=0,
                error=str(e),
                duration_seconds=duration,
            )
        finally:
            metrics.decrement_active_scans()
    
    async def scan_categories_parallel(
        self,
        categories: List[Dict[str, Any]],
        job_id: Optional[int] = None,
        on_result: Optional[Callable[[ScanResult], None]] = None,
    ) -> ScanProgress:
        """
        Scan multiple categories in parallel with concurrency limit.
        
        Args:
            categories: List of category dicts to scan
            job_id: Optional job ID for tracking
            on_result: Optional callback for each result
            
        Returns:
            ScanProgress with all results
        """
        progress = ScanProgress(
            job_id=job_id or 0,
            total_categories=len(categories),
        )
        
        if job_id:
            self._active_jobs[job_id] = progress
        
        # Create semaphore for concurrency limit
        semaphore = asyncio.Semaphore(self.max_parallel_scans)
        
        async def scan_with_semaphore(category: Dict[str, Any]) -> ScanResult:
            async with semaphore:
                # Build filter config from category settings
                filter_config = FilterConfig.from_json_fields(
                    keywords_json=category.get("keywords"),
                    exclude_keywords_json=category.get("exclude_keywords"),
                    brands_json=category.get("brands"),
                    min_price=category.get("min_price"),
                    max_price=category.get("max_price"),
                )
                
                result = await self.scan_category(category, filter_config)
                
                # Update progress
                progress.completed_categories += 1
                progress.total_products += result.products_found
                progress.total_deals += result.deals_found
                progress.results.append(result)
                
                if result.error:
                    progress.errors.append(f"{result.category_name}: {result.error}")
                
                # Notify progress
                self._notify_progress(progress)
                
                # Call result callback if provided
                if on_result:
                    on_result(result)
                
                return result
        
        # Run all scans with concurrency limit
        tasks = [scan_with_semaphore(cat) for cat in categories]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Cleanup
        if job_id and job_id in self._active_jobs:
            del self._active_jobs[job_id]
        
        return progress
    
    def _calculate_effective_interval(self, cat: StoreCategory) -> int:
        """
        Calculate effective scan interval based on priority and success rate.
        
        Uses configurable multipliers:
        - Priority 8-10: base interval (1x)
        - Priority 5-7: 1.5x interval
        - Priority 1-4: 2x interval
        
        Additional adjustments:
        - Categories with no recent deals: +25% interval
        - Categories with many deals (>=5): -20% interval
        - Categories in unhealthy stores: +50% interval
        
        Args:
            cat: StoreCategory model
            
        Returns:
            Effective interval in minutes
        """
        base_interval = cat.scan_interval_minutes
        
        # Priority-based multiplier
        if cat.priority >= 8:
            multiplier = settings.priority_high_multiplier
        elif cat.priority >= 5:
            multiplier = settings.priority_medium_multiplier
        else:
            multiplier = settings.priority_low_multiplier
        
        # Adjust based on deal yield
        deals_found = cat.deals_found or 0
        if deals_found == 0 and cat.last_scanned:
            # No deals found = slow down
            multiplier *= settings.no_deals_penalty
        elif deals_found >= 5:
            # High yield category = speed up
            multiplier *= settings.success_rate_boost
        
        # Adjust based on store health
        if not store_health.is_store_healthy(cat.store):
            # Unhealthy store = slow down significantly
            multiplier *= 1.5
        
        # Adjust based on product age (new products need more frequent scanning)
        # This would require checking products in the category
        # For now, use category name to detect "new arrivals"
        if "new" in cat.category_name.lower() or "arrival" in cat.category_name.lower():
            multiplier *= 0.5  # Scan new arrivals twice as often
        
        # Adjust based on price volatility (would need product volatility data)
        # High volatility categories (electronics, flash sales) need more frequent scanning
        volatile_keywords = ["flash", "lightning", "deal", "sale", "clearance"]
        if any(keyword in cat.category_name.lower() for keyword in volatile_keywords):
            multiplier *= 0.7  # Scan volatile categories more often
        
        effective_interval = int(base_interval * multiplier)
        
        # Never go below the base interval
        effective_interval = max(effective_interval, base_interval)
        
        # Minimum interval: never scan same product <1 minute apart
        effective_interval = max(effective_interval, 1)
        
        return effective_interval
    
    def _calculate_scan_priority(self, cat: StoreCategory) -> float:
        """
        Calculate scan priority score for scheduling.
        
        Higher score = higher priority for scanning.
        
        Args:
            cat: Store category
            
        Returns:
            Priority score (higher = more important)
        """
        score = float(cat.priority)  # Base priority (1-10)
        
        # Boost for categories that find deals
        deals_found = cat.deals_found or 0
        if deals_found >= 5:
            score += 2.0
        elif deals_found > 0:
            score += 1.0
        
        # Boost for high-value categories
        category_lower = cat.category_name.lower() if cat.category_name else ""
        if any(x in category_lower for x in ["electronics", "computer", "gaming"]):
            score += 1.5
        
        # Penalize for recent errors
        if cat.last_error and cat.last_error_at:
            hours_since_error = (datetime.utcnow() - cat.last_error_at).total_seconds() / 3600
            if hours_since_error < 1:
                score -= 2.0  # Recent error, lower priority
            elif hours_since_error < 6:
                score -= 1.0
        
        return max(0.0, score)
    
    def _is_category_due_for_scan(self, cat: StoreCategory, now: datetime) -> bool:
        """Check if category is due for scanning based on last scan time and priority."""
        if not cat.last_scanned:
            return True
        
        effective_interval = self._calculate_effective_interval(cat)
        next_scan = cat.last_scanned + timedelta(minutes=effective_interval)
        return now >= next_scan
    
    def _is_category_in_cooldown(self, cat: StoreCategory, now: datetime) -> bool:
        """Check if category is in error cooldown period."""
        if not cat.last_error or not cat.last_error_at:
            return False
        
        cooldown_seconds = _get_error_cooldown_seconds(cat.last_error)
        if not cooldown_seconds:
            return False
        
        cooldown_until = cat.last_error_at + timedelta(seconds=cooldown_seconds)
        if now < cooldown_until:
            logger.info(
                "Skipping category %s (%s) due to recent error: %s",
                cat.category_name,
                cat.store,
                cat.last_error,
            )
            return True
        
        return False
    
    def _build_category_dict(self, cat: StoreCategory) -> Dict[str, Any]:
        """Build category data dict from StoreCategory model."""
        return {
            "id": cat.id,
            "store": cat.store,
            "category_name": cat.category_name,
            "category_url": cat.category_url,
            "max_pages": cat.max_pages,
            "keywords": cat.keywords,
            "exclude_keywords": cat.exclude_keywords,
            "brands": cat.brands,
            "min_price": cat.min_price,
            "max_price": cat.max_price,
            "min_discount_percent": cat.min_discount_percent or 50.0,
        }
    
    async def _get_categories_due_for_scan(self, db: AsyncSession) -> List[Dict[str, Any]]:
        """Get list of categories that are due for scanning."""
        query = (
            select(StoreCategory)
            .where(StoreCategory.enabled == True)
            .order_by(
                StoreCategory.priority.desc(),
                StoreCategory.last_scanned.asc().nullsfirst()
            )
        )
        result = await db.execute(query)
        categories = result.scalars().all()
        
        # Sort by calculated priority score (highest first)
        categories = sorted(
            categories,
            key=lambda c: self._calculate_scan_priority(c),
            reverse=True
        )
        
        now = datetime.utcnow()
        categories_data = []
        
        for cat in categories:
            if not self._is_category_due_for_scan(cat, now):
                continue
            
            if self._is_category_in_cooldown(cat, now):
                continue
            
            categories_data.append(self._build_category_dict(cat))
        
        return categories_data
    
    async def run_scheduled_scan(self) -> ScanProgress:
        """
        Run a scheduled scan of all enabled categories.
        Uses smart scheduling based on priority and last scan time.
        """
        # Load exclusions
        async with AsyncSessionLocal() as db:
            await exclusion_manager.load_exclusions(db)
        
        # Get categories due for scanning
        async with AsyncSessionLocal() as db:
            categories_data = await self._get_categories_due_for_scan(db)
            
            # Create scan job
            job = await self.create_scan_job(
                db, 
                job_type="scheduled",
                total_items=len(categories_data)
            )
            job_id = job.id
        
        if not categories_data:
            logger.info("No categories due for scanning")
            return ScanProgress(job_id=job_id, total_categories=0)
        
        logger.info(f"Starting scheduled scan of {len(categories_data)} categories")
        
        # Update job status
        async with AsyncSessionLocal() as db:
            await self.update_scan_job(
                db,
                job_id,
                status="running",
                started_at=datetime.utcnow(),
            )
        
        # Batch category stat updates for better performance
        batch_size = getattr(settings, 'db_batch_update_size', 10)
        pending_updates: List[ScanResult] = []
        pending_updates_lock = asyncio.Lock()
        last_batch_task = None
        
        def _is_404_error(error_message: str) -> bool:
            """Check if error message indicates a 404/410 error."""
            error_lower = error_message.lower()
            return (
                "http 404" in error_lower or
                "http 410" in error_lower or
                "404 not found" in error_lower or
                "page not found" in error_lower or
                (error_lower.count("404") > 0 and "not found" in error_lower)
            )
        
        def _update_category_from_result(cat: StoreCategory, scan_result: ScanResult, scan_time: datetime):
            """Update category model from scan result."""
            cat.last_scanned = scan_time
            cat.products_found = scan_result.products_found
            cat.deals_found = scan_result.deals_found
            
            if scan_result.error:
                cat.last_error = scan_result.error
                cat.last_error_at = scan_time
                if settings.category_disable_on_404 and _is_404_error(scan_result.error):
                    logger.warning(
                        "Auto-disabling category %s (%s) due to 404/410 error: %s",
                        cat.category_name,
                        cat.store,
                        scan_result.error
                    )
                    cat.enabled = False
            else:
                cat.last_error = None
                cat.last_error_at = None
        
        async def batch_update_category_stats():
            """Batch update category stats to reduce database overhead."""
            async with pending_updates_lock:
                if not pending_updates:
                    return
                
                # Copy and clear pending_updates atomically
                updates_to_process = pending_updates.copy()
                pending_updates.clear()
            
            async with AsyncSessionLocal() as db:
                # Get all categories in one query
                category_ids = [r.category_id for r in updates_to_process]
                query = select(StoreCategory).where(StoreCategory.id.in_(category_ids))
                result = await db.execute(query)
                categories = {cat.id: cat for cat in result.scalars().all()}
                
                scan_time = datetime.utcnow()
                for scan_result in updates_to_process:
                    cat = categories.get(scan_result.category_id)
                    if cat:
                        _update_category_from_result(cat, scan_result, scan_time)
                
                await db.commit()
        
        def on_result_callback(result: ScanResult):
            """Callback to collect results for batch updating."""
            nonlocal last_batch_task
            
            # Append with lock protection (synchronous operation on the list)
            # We need to schedule the async lock acquisition
            async def append_with_lock():
                async with pending_updates_lock:
                    pending_updates.append(result)
                    should_trigger = len(pending_updates) >= batch_size
                
                if should_trigger:
                    task = asyncio.create_task(batch_update_category_stats())
                    # Store task reference and handle exceptions
                    def handle_task_done(task):
                        try:
                            task.result()
                        except Exception:
                            logger.exception("Error in batch_update_category_stats")
                    task.add_done_callback(handle_task_done)
                    return task
                return None
            
            # Schedule the async append operation
            append_task = asyncio.create_task(append_with_lock())
            # Store reference and handle errors without blocking
            def handle_append_done(task):
                try:
                    batch_task = task.result()
                    if batch_task:
                        nonlocal last_batch_task
                        last_batch_task = batch_task
                except Exception:
                    logger.exception("Error in on_result_callback")
            append_task.add_done_callback(handle_append_done)
        
        # Run parallel scan
        progress = await self.scan_categories_parallel(
            categories_data,
            job_id=job_id,
            on_result=on_result_callback
        )
        
        # Process any remaining pending updates
        # Check and capture state inside lock, then release before calling batch_update_category_stats
        # to avoid deadlock (batch_update_category_stats also acquires the lock)
        async with pending_updates_lock:
            has_pending = bool(pending_updates)
            captured_batch_task = last_batch_task
        
        # After releasing lock, wait for in-flight task and process remaining updates
        if captured_batch_task and not captured_batch_task.done():
            try:
                await captured_batch_task
            except Exception:
                logger.exception("Error waiting for last batch task")
        
        if has_pending:
            await batch_update_category_stats()
        
        # Update job completion
        async with AsyncSessionLocal() as db:
            await self.update_scan_job(
                db,
                job_id,
                status="completed",
                completed_at=datetime.utcnow(),
                processed_items=progress.completed_categories,
                success_count=progress.completed_categories - len(progress.errors),
                error_count=len(progress.errors),
                products_found=progress.total_products,
                deals_found=progress.total_deals,
                error_message="\n".join(progress.errors) if progress.errors else None,
            )
        
        logger.info(
            f"Scheduled scan complete: {progress.total_products} products, "
            f"{progress.total_deals} deals from {progress.completed_categories} categories"
        )
        
        return progress
    
    async def trigger_manual_scan(
        self,
        category_ids: Optional[List[int]] = None,
        store: Optional[str] = None,
    ) -> ScanProgress:
        """
        Trigger a manual scan for specific categories or store.
        
        Args:
            category_ids: Specific category IDs to scan
            store: Scan all categories for this store
            
        Returns:
            ScanProgress with results
        """
        # Load exclusions
        async with AsyncSessionLocal() as db:
            await exclusion_manager.load_exclusions(db)
        
        # Get categories to scan
        categories_data = []
        async with AsyncSessionLocal() as db:
            query = select(StoreCategory).where(StoreCategory.enabled == True)
            
            if category_ids:
                query = query.where(StoreCategory.id.in_(category_ids))
            elif store:
                query = query.where(StoreCategory.store == store)
            
            result = await db.execute(query)
            categories = result.scalars().all()
            
            for cat in categories:
                categories_data.append({
                    "id": cat.id,
                    "store": cat.store,
                    "category_name": cat.category_name,
                    "category_url": cat.category_url,
                    "max_pages": cat.max_pages,
                    "keywords": cat.keywords,
                    "exclude_keywords": cat.exclude_keywords,
                    "brands": cat.brands,
                    "min_price": cat.min_price,
                    "max_price": cat.max_price,
                    "min_discount_percent": cat.min_discount_percent or 50.0,
                })
            
            # Create job
            job = await self.create_scan_job(
                db,
                job_type="manual",
                total_items=len(categories_data)
            )
            job_id = job.id
        
        if not categories_data:
            logger.info("No categories found for manual scan")
            return ScanProgress(job_id=job_id, total_categories=0)
        
        logger.info(f"Starting manual scan of {len(categories_data)} categories")
        
        # Update job status
        async with AsyncSessionLocal() as db:
            await self.update_scan_job(
                db,
                job_id,
                status="running",
                started_at=datetime.utcnow(),
            )
        
        # Run parallel scan
        progress = await self.scan_categories_parallel(
            categories_data,
            job_id=job_id,
        )
        
        # Update job completion
        async with AsyncSessionLocal() as db:
            await self.update_scan_job(
                db,
                job_id,
                status="completed",
                completed_at=datetime.utcnow(),
                processed_items=progress.completed_categories,
                success_count=progress.completed_categories - len(progress.errors),
                error_count=len(progress.errors),
                products_found=progress.total_products,
                deals_found=progress.total_deals,
            )
        
        return progress
    
    def get_active_job(self, job_id: int) -> Optional[ScanProgress]:
        """Get progress of an active job."""
        return self._active_jobs.get(job_id)
    
    def get_all_active_jobs(self) -> Dict[int, ScanProgress]:
        """Get all active jobs."""
        return dict(self._active_jobs)


# Global scan engine instance (uses configurable setting from settings)
scan_engine = ScanEngine()
