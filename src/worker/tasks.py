"""Background tasks for category-based deal discovery."""

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert, PriceHistory, Product, Webhook
from src.db.session import AsyncSessionLocal
from src.detect.engine import DetectionEngine
from src.notify.dedupe import DedupeManager
from src.notify.discord import DiscordWebhook
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

        except Exception as e:
            logger.error(f"Category scan failed: {e}")
            raise

    async def _process_discovered_deal(self, deal):
        """
        Process a discovered deal.
        
        - Adds new product to database if not already tracked
        - Sends Discord alert for significant deals
        """
        from src.detect.deal_detector import DetectedDeal

        deal: DetectedDeal = deal
        product_data = deal.product

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
                    # Product already tracked, skip
                    logger.debug(f"Product {product_data.sku} already tracked")
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

                # Add initial price history
                price_history = PriceHistory(
                    product_id=new_product.id,
                    price=product_data.current_price,
                    original_price=product_data.original_price,
                    confidence=deal.confidence,
                )
                db.add(price_history)
                await db.commit()

                logger.info(
                    f"Added discovered deal: {product_data.title[:50]} at ${product_data.current_price} "
                    f"({deal.discount_percent:.1f}% off)"
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
        """Send Discord alert for a discovered deal."""
        from src.detect.deal_detector import DetectedDeal

        deal: DetectedDeal = deal

        # Get enabled webhooks
        webhook_query = select(Webhook).where(Webhook.enabled == True)
        webhook_result = await db.execute(webhook_query)
        webhooks = webhook_result.scalars().all()

        if not webhooks:
            logger.debug("No webhooks configured, skipping deal alert")
            return

        for webhook_model in webhooks:
            try:
                webhook = DiscordWebhook(webhook_model.url)

                # Format alert reason
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
                    image_url=product.image_url or deal.product.image_url,  # Pass image URL
                )

                await webhook.close()

                logger.info(f"Sent deal alert for {product.sku}: {deal.discount_percent:.1f}% off")

            except Exception as e:
                logger.error(f"Failed to send deal webhook: {e}")


# Global task runner instance
task_runner = TaskRunner()
