"""Background tasks for category-based deal discovery."""

import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert, PriceHistory, Product, Webhook
from src.db.session import AsyncSessionLocal
from src.detect.engine import DetectionEngine
from src.detect.baseline import baseline_calculator
from src.detect.deal_detector import enhance_deal_with_anomaly
from src.notify.dedupe import DedupeManager
from src.notify.discord import DiscordWebhook
from src.notify.webhook_manager import webhook_manager
from src.notify.cross_source_dedupe import cross_source_deduper
from src.api.routes.dashboard import add_scan_entry

logger = logging.getLogger(__name__)


class TaskRunner:
    """
    Runner for background tasks.
    
    Category-first approach:
    - Scans store category pages to discover deals
    - No individual product tracking required
    - Deals are automatically detected and alerted
    """

    def __init__(self):
        self.dedupe_manager: DedupeManager | None = None
        self._scan_lock = asyncio.Lock()

    async def initialize(self):
        """Initialize task runner."""
        from src.config import settings

        self.dedupe_manager = DedupeManager(settings.redis_url)
        logger.info("Task runner initialized")

    async def close(self):
        """Clean up resources."""
        if self.dedupe_manager:
            await self.dedupe_manager.close()

    async def recalculate_baselines(self):
        """Recalculate baseline prices for discovered products."""
        logger.info("Recalculating baseline prices")

        # Load product IDs first to avoid session expiry issues
        product_ids = []
        async with AsyncSessionLocal() as db:
            query = select(Product.id, Product.sku)
            result = await db.execute(query)
            product_ids = [(row[0], row[1]) for row in result.all()]

        if not product_ids:
            logger.info("No products to recalculate baselines for")
            return

        # Process each product with a fresh session
        for product_id, sku in product_ids:
            try:
                async with AsyncSessionLocal() as db:
                    engine = DetectionEngine(db)
                    await engine.update_baseline_price(product_id)
            except Exception as e:
                logger.error(f"Failed to update baseline for {sku}: {e}")

        logger.info(f"Completed baseline recalculation for {len(product_ids)} products")

    async def scan_store_categories(self):
        """
        Scan enabled store categories for deals.
        
        This is the main scanning method that:
        1. Scans category pages from configured stores
        2. Discovers products and their prices
        3. Detects deals based on discounts
        4. Sends alerts for significant deals
        """
        from src.ingest.scan_engine import scan_engine

        logger.info("Starting category scan for deals")

        try:
            # Atomic try-acquire pattern to avoid race condition
            try:
                # Attempt non-blocking acquire
                await asyncio.wait_for(self._scan_lock.acquire(), timeout=0)
            except asyncio.TimeoutError:
                # Lock is already held, scan is running
                logger.info("Scan already running; skipping scheduled run")
                return
            
            try:
                # Use the scan engine for parallel scanning with filtering
                progress = await scan_engine.run_scheduled_scan()

                # Process discovered deals
                for result in progress.results:
                    if result.deals:
                        for deal in result.deals:
                            await self._process_discovered_deal(deal)

                logger.info(
                    f"Category scan complete: {progress.total_products} products, "
                    f"{progress.total_deals} deals from {progress.completed_categories} categories"
                )

                if progress.errors:
                    logger.warning(f"Scan had {len(progress.errors)} errors")
            finally:
                # Always release the lock
                self._scan_lock.release()

        except Exception as e:
            logger.error(f"Category scan failed: {e}")
            raise

    async def _process_discovered_deal(self, deal):
        """
        Process a discovered deal.
        
        - Checks cross-source deduplication (only notify best price across aggregators)
        - Enhances deal with anomaly detection scores
        - Adds new product to database if not already tracked
        - Records price history for baseline calculations
        - Sends alerts via webhook manager for significant deals
        """
        from src.detect.deal_detector import DetectedDeal

        deal: DetectedDeal = deal
        product_data = deal.product

        # Check cross-source deduplication for deal aggregators
        # This ensures we only notify for the best price when the same product
        # appears on multiple aggregator sites (SaveYourDeals, Slickdeals, Woot)
        if product_data.current_price:
            should_notify = await cross_source_deduper.should_notify(
                sku=product_data.sku,
                store=product_data.store,
                price=product_data.current_price,
                url=product_data.url or ""
            )
            if not should_notify:
                logger.debug(
                    f"Skipping {product_data.sku} from {product_data.store}: "
                    f"better price exists from another source"
                )
                return

        try:
            async with AsyncSessionLocal() as db:
                # Check if product already exists
                existing_query = select(Product).where(
                    Product.store == product_data.store,
                    Product.sku == product_data.sku
                )
                existing_result = await db.execute(existing_query)
                existing = existing_result.scalar_one_or_none()

                if existing:
                    # Product exists - enhance deal with anomaly detection using history
                    deal = await enhance_deal_with_anomaly(deal, db)
                    
                    # Update structured attributes if title changed or attributes missing
                    if settings.ai_attribute_extraction_enabled and product_data.title:
                        if not existing.structured_attributes or existing.title != product_data.title:
                            try:
                                from src.ai.attribute_extractor import attribute_extractor
                                from src.db.models import ProductAttributes
                                
                                attributes = await attribute_extractor.extract_attributes(
                                    title=product_data.title,
                                    description=None,
                                    use_llm=settings.ai_attribute_extraction_enabled,
                                )
                                
                                if attributes:
                                    existing.structured_attributes = attributes
                                    
                                    # Update or create ProductAttributes record
                                    attrs_query = select(ProductAttributes).where(
                                        ProductAttributes.product_id == existing.id
                                    )
                                    attrs_result = await db.execute(attrs_query)
                                    product_attrs = attrs_result.scalar_one_or_none()
                                    
                                    if product_attrs:
                                        product_attrs.brand = attributes.get("brand")
                                        product_attrs.model = attributes.get("model")
                                        product_attrs.size = attributes.get("size")
                                        product_attrs.color = attributes.get("color")
                                        product_attrs.category = attributes.get("category")
                                        product_attrs.raw_attributes = attributes
                                    else:
                                        product_attrs = ProductAttributes(
                                            product_id=existing.id,
                                            brand=attributes.get("brand"),
                                            model=attributes.get("model"),
                                            size=attributes.get("size"),
                                            color=attributes.get("color"),
                                            category=attributes.get("category"),
                                            extraction_method="rule",
                                            raw_attributes=attributes,
                                        )
                                        db.add(product_attrs)
                            except Exception as e:
                                logger.warning(f"Failed to update attributes for product {existing.id}: {e}")
                    
                    # Record price observation for baseline tracking
                    await baseline_calculator.update_baseline(
                        db,
                        existing.id,
                        product_data.current_price,
                        product_data.original_price,
                    )
                    
                    # If this is a significant deal, still alert
                    if deal.is_significant:
                        await self._send_deal_alert(db, existing, deal)
                    return

                # Add new product
                new_product = Product(
                    sku=product_data.sku,
                    store=product_data.store,
                    title=product_data.title,
                    url=product_data.url,
                    image_url=product_data.image_url,  # Store product image
                    msrp=product_data.original_price or product_data.msrp,
                    baseline_price=product_data.current_price,
                )
                db.add(new_product)
                await db.flush()
                
                # Extract and store structured attributes if enabled
                if settings.ai_attribute_extraction_enabled and product_data.title:
                    try:
                        from src.ai.attribute_extractor import attribute_extractor
                        from src.db.models import ProductAttributes
                        
                        attributes = attribute_extractor.extract_attributes(
                            title=product_data.title,
                            description=None,
                            use_llm=settings.ai_attribute_extraction_enabled,
                        )
                        
                        if attributes:
                            # Store in structured_attributes JSONB column
                            new_product.structured_attributes = attributes
                            
                            # Also create ProductAttributes record
                            product_attrs = ProductAttributes(
                                product_id=new_product.id,
                                brand=attributes.get("brand"),
                                model=attributes.get("model"),
                                size=attributes.get("size"),
                                color=attributes.get("color"),
                                category=attributes.get("category"),
                                extraction_method="rule",  # or "llm" if LLM was used
                                raw_attributes=attributes,
                            )
                            db.add(product_attrs)
                    except Exception as e:
                        logger.warning(f"Failed to extract attributes for product {new_product.id}: {e}")

                # Add initial price history
                price_history = PriceHistory(
                    product_id=new_product.id,
                    price=product_data.current_price,
                    original_price=product_data.original_price,
                    confidence=deal.confidence,
                )
                db.add(price_history)
                await db.commit()
                
                # Generate and store embedding for semantic matching (async, don't block)
                if settings.ai_product_matching_enabled and settings.vector_db_enabled:
                    try:
                        from src.ai.product_matcher import product_matcher
                        await product_matcher.store_embedding(db, new_product)
                        await db.commit()
                    except Exception as e:
                        logger.warning(f"Failed to generate embedding for product {new_product.id}: {e}")
                        # Don't fail the whole operation if embedding fails

                logger.info(
                    f"Added discovered deal: {product_data.title[:50] if product_data.title else 'N/A'} "
                    f"at ${product_data.current_price} ({deal.discount_percent:.1f}% off)"
                )

                # Add scan entry for dashboard
                add_scan_entry(
                    product_data.store,
                    product_data.sku,
                    product_data.title,
                    "success",
                    price=float(product_data.current_price),
                    previous_price=float(product_data.original_price) if product_data.original_price else None,
                )

                # Send alert for significant deals (40%+ off with good confidence)
                if deal.is_significant:
                    await self._send_deal_alert(db, new_product, deal)

        except Exception as e:
            logger.error(f"Failed to process discovered deal: {e}")

    async def _send_deal_alert(self, db: AsyncSession, product: Product, deal):
        """Send alert for a discovered deal to all configured webhooks."""
        from src.detect.deal_detector import DetectedDeal

        deal: DetectedDeal = deal

        try:
            # Use webhook manager for multi-platform support
            results = await webhook_manager.send_alert(db, deal)
            
            successful = sum(1 for success in results.values() if success)
            failed = len(results) - successful
            
            if successful > 0:
                anomaly_info = ""
                if deal.anomaly_score is not None:
                    anomaly_info = f", anomaly score: {deal.anomaly_score:.2f}"
                
                logger.info(
                    f"Sent deal alert for {product.sku}: {deal.discount_percent:.1f}% off "
                    f"(confidence: {deal.confidence:.2f}{anomaly_info}) "
                    f"to {successful}/{len(results)} webhooks"
                )
            
            if failed > 0:
                logger.warning(f"{failed} webhooks failed for {product.sku}")

        except Exception as e:
            logger.error(f"Failed to send deal alerts: {e}")
            
            # Fallback to direct Discord webhook if webhook manager fails
            try:
                webhook_query = select(Webhook).where(
                    Webhook.enabled == True,
                    Webhook.webhook_type == "discord"
                )
                webhook_result = await db.execute(webhook_query)
                webhooks = webhook_result.scalars().all()

                for webhook_model in webhooks:
                    try:
                        webhook = DiscordWebhook(webhook_model.url)
                        reason_emoji = "🔥" if deal.discount_percent >= 60 else "💰"
                        reason = f"{reason_emoji} DEAL: {deal.reason}"

                        await webhook.send_price_alert(
                            product_title=product.title,
                            product_url=product.url,
                            sku=product.sku,
                            store=product.store,
                            current_price=deal.product.current_price,
                            previous_price=deal.product.original_price,
                            baseline_price=deal.product.original_price,
                            msrp=deal.product.msrp or deal.product.original_price,
                            reason=reason,
                            confidence=deal.confidence,
                            image_url=product.image_url or deal.product.image_url,
                        )
                        await webhook.close()
                    except Exception as fallback_error:
                        logger.error(f"Fallback webhook also failed: {fallback_error}")
            except Exception as fallback_e:
                logger.error(f"Fallback mechanism failed: {fallback_e}")


# Global task runner instance
task_runner = TaskRunner()
