"""Enhanced scan engine with parallel scanning and progress tracking."""

import asyncio
import logging
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import StoreCategory, ScanJob, ProductExclusion
from src.db.session import AsyncSessionLocal
from src.ingest.category_scanner import CategoryScanner, DiscoveredProduct
from src.ingest.filters import (
    FilterConfig,
    ProductFilter,
    exclusion_manager,
    filter_low_cost_kids_items,
)
from src.config import settings
from src.detect.deal_detector import deal_detector, DetectedDeal

logger = logging.getLogger(__name__)


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
        max_parallel_scans: int = 3,
        scanner: Optional[CategoryScanner] = None,
    ):
        self.max_parallel_scans = max_parallel_scans
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
        
        try:
            # Build category URL
            category_url = category["category_url"]
            store = category["store"]
            max_pages = category.get("max_pages", 5)
            
            # Add base URL if relative
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
            
            # Scan the category
            products = await self.scanner.scan_category(
                store=store,
                category_url=category_url,
                max_pages=max_pages,
            )
            
            # Apply filters if configured
            if filter_config:
                product_filter = ProductFilter(filter_config)
                products = product_filter.filter_products(products)
            
            # Check global exclusions
            products = [p for p in products if not exclusion_manager.is_excluded(p)]
            products = filter_low_cost_kids_items(products)

            # Enforce global minimum price (prioritize high ticket items)
            if getattr(settings, "global_min_price", 0) and settings.global_min_price > 0:
                min_price = Decimal(str(settings.global_min_price))
                products = [
                    p for p in products
                    if p.current_price is not None and p.current_price >= min_price
                ]
            
            # Detect deals
            min_discount = category.get("min_discount_percent", 50.0)
            if getattr(settings, "global_min_discount_percent", 0) and settings.global_min_discount_percent > 0:
                min_discount = max(min_discount, settings.global_min_discount_percent)
            deals = deal_detector.detect_deals_batch(products, min_confidence=0.5)
            significant_deals = [d for d in deals if d.discount_percent >= min_discount]
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            return ScanResult(
                category_id=category["id"],
                category_name=category["category_name"],
                store=store,
                products_found=len(products),
                deals_found=len(significant_deals),
                products=products,
                deals=significant_deals,
                duration_seconds=duration,
            )
            
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"Scan failed for category {category.get('category_name')}: {e}")
            return ScanResult(
                category_id=category["id"],
                category_name=category.get("category_name", "Unknown"),
                store=category.get("store", "Unknown"),
                products_found=0,
                deals_found=0,
                error=str(e),
                duration_seconds=duration,
            )
    
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
    
    async def run_scheduled_scan(self) -> ScanProgress:
        """
        Run a scheduled scan of all enabled categories.
        Uses smart scheduling based on priority and last scan time.
        """
        # Load exclusions
        async with AsyncSessionLocal() as db:
            await exclusion_manager.load_exclusions(db)
        
        # Get categories ordered by priority and last scan time
        categories_data = []
        async with AsyncSessionLocal() as db:
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
            
            # Filter to only scan categories that are due
            now = datetime.utcnow()
            for cat in categories:
                # Check if due for scan
                if cat.last_scanned:
                    from datetime import timedelta
                    next_scan = cat.last_scanned + timedelta(minutes=cat.scan_interval_minutes)
                    if now < next_scan:
                        continue
                
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
        
        # Callback to update category stats
        async def update_category_stats(result: ScanResult):
            async with AsyncSessionLocal() as db:
                cat = await db.get(StoreCategory, result.category_id)
                if cat:
                    scan_time = datetime.utcnow()
                    cat.last_scanned = scan_time
                    cat.products_found = result.products_found
                    cat.deals_found = result.deals_found
                    if result.error:
                        cat.last_error = result.error
                        cat.last_error_at = scan_time
                    else:
                        cat.last_error = None
                        cat.last_error_at = None
                    await db.commit()
        
        # Run parallel scan
        progress = await self.scan_categories_parallel(
            categories_data,
            job_id=job_id,
            on_result=lambda r: asyncio.create_task(update_category_stats(r))
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


# Global scan engine instance
scan_engine = ScanEngine(max_parallel_scans=3)
