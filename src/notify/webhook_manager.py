"""Multi-platform webhook manager for notifications.

Supports Discord, Telegram, Slack, and generic webhooks with
customizable templates and filtering.
"""

import json
import logging
import time
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Webhook, NotificationHistory
from src.detect.deal_detector import DetectedDeal

logger = logging.getLogger(__name__)


class WebhookType(Enum):
    """Supported webhook types."""
    DISCORD = "discord"
    TELEGRAM = "telegram"
    SLACK = "slack"
    GENERIC = "generic"


class WebhookManager:
    """
    Manages multi-platform webhook notifications.
    
    Supports:
    - Discord webhooks (embed format)
    - Telegram Bot API
    - Slack webhooks (Block Kit format)
    - Generic webhooks (custom JSON payload)
    """
    
    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client
    
    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    async def send_alert(
        self,
        db: AsyncSession,
        deal: DetectedDeal,
        webhooks: Optional[List[Webhook]] = None,
    ) -> Dict[int, bool]:
        """
        Send alert to all matching webhooks.
        
        Args:
            db: Database session
            deal: Detected deal to alert
            webhooks: Optional list of webhooks (fetches enabled if None)
            
        Returns:
            Dict mapping webhook ID to success status
        """
        if webhooks is None:
            webhooks = await self._get_enabled_webhooks(db)
        
        results = {}
        
        for webhook in webhooks:
            if not self._matches_filters(webhook, deal):
                continue
            
            try:
                success = await self._send_to_webhook(db, webhook, deal)
                results[webhook.id] = success
            except Exception as e:
                logger.error(f"Error sending to webhook {webhook.id}: {e}")
                results[webhook.id] = False
        
        return results
    
    async def _get_enabled_webhooks(self, db: AsyncSession) -> List[Webhook]:
        """Get all enabled webhooks."""
        query = select(Webhook).where(Webhook.enabled == True)
        result = await db.execute(query)
        return list(result.scalars().all())
    
    def _matches_filters(self, webhook: Webhook, deal: DetectedDeal) -> bool:
        """Check if deal matches webhook filters."""
        if not webhook.filters:
            return True
        
        try:
            filters = json.loads(webhook.filters)
        except json.JSONDecodeError:
            return True
        
        # Check minimum discount
        min_discount = filters.get("min_discount")
        if min_discount and deal.discount_percent < min_discount:
            return False
        
        # Check store filter
        stores = filters.get("stores")
        if stores and deal.product.store not in stores:
            return False
        
        # Check category filter
        categories = filters.get("categories")
        if categories and deal.category:
            if not any(cat.lower() in deal.category.lower() for cat in categories):
                return False
        
        # Check minimum confidence
        min_confidence = filters.get("min_confidence")
        if min_confidence and deal.confidence < min_confidence:
            return False
        
        return True
    
    async def _send_to_webhook(
        self,
        db: AsyncSession,
        webhook: Webhook,
        deal: DetectedDeal,
    ) -> bool:
        """Send notification to a specific webhook."""
        webhook_type = WebhookType(webhook.webhook_type)
        
        start_time = time.monotonic()
        success = False
        error_message = None
        response_text = None
        payload = None
        
        try:
            if webhook_type == WebhookType.DISCORD:
                success, payload = await self._send_discord(webhook, deal)
            elif webhook_type == WebhookType.TELEGRAM:
                success, payload = await self._send_telegram(webhook, deal)
            elif webhook_type == WebhookType.SLACK:
                success, payload = await self._send_slack(webhook, deal)
            elif webhook_type == WebhookType.GENERIC:
                success, payload = await self._send_generic(webhook, deal)
            else:
                error_message = f"Unknown webhook type: {webhook.webhook_type}"
                
        except Exception as e:
            error_message = str(e)
            logger.error(f"Webhook send failed: {e}")
        
        response_time_ms = int((time.monotonic() - start_time) * 1000)
        
        # Update webhook stats
        if success:
            webhook.send_count += 1
            webhook.last_sent_at = datetime.utcnow()
        else:
            webhook.error_count += 1
        
        # Record notification history
        history = NotificationHistory(
            webhook_id=webhook.id,
            notification_type="alert",
            status="sent" if success else "failed",
            payload=json.dumps(payload) if payload else None,
            response=response_text,
            error_message=error_message,
            sent_at=datetime.utcnow(),
            response_time_ms=response_time_ms,
        )
        db.add(history)
        await db.commit()
        
        return success
    
    async def _send_discord(
        self,
        webhook: Webhook,
        deal: DetectedDeal,
    ) -> tuple[bool, dict]:
        """Send notification to Discord webhook."""
        from src.notify.formatters import format_discord_embed
        
        payload = format_discord_embed(deal, webhook.template)
        
        client = await self._get_client()
        response = await client.post(webhook.url, json=payload)
        
        success = response.status_code in (200, 204)
        if not success:
            logger.warning(f"Discord webhook failed: {response.status_code} - {response.text}")
        
        return success, payload
    
    async def _send_telegram(
        self,
        webhook: Webhook,
        deal: DetectedDeal,
    ) -> tuple[bool, dict]:
        """Send notification to Telegram."""
        from src.notify.formatters import format_telegram_message
        
        if not webhook.telegram_chat_id or not webhook.telegram_bot_token:
            raise ValueError("Telegram webhook missing chat_id or bot_token")
        
        message = format_telegram_message(deal, webhook.template)
        
        url = f"https://api.telegram.org/bot{webhook.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": webhook.telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }
        
        client = await self._get_client()
        response = await client.post(url, json=payload)
        
        success = response.status_code == 200
        if not success:
            logger.warning(f"Telegram send failed: {response.status_code} - {response.text}")
        
        return success, payload
    
    async def _send_slack(
        self,
        webhook: Webhook,
        deal: DetectedDeal,
    ) -> tuple[bool, dict]:
        """Send notification to Slack webhook."""
        from src.notify.formatters import format_slack_blocks
        
        payload = format_slack_blocks(deal, webhook.template)
        
        client = await self._get_client()
        response = await client.post(webhook.url, json=payload)
        
        success = response.status_code == 200
        if not success:
            logger.warning(f"Slack webhook failed: {response.status_code} - {response.text}")
        
        return success, payload
    
    async def _send_generic(
        self,
        webhook: Webhook,
        deal: DetectedDeal,
    ) -> tuple[bool, dict]:
        """Send notification to generic webhook."""
        from src.notify.formatters import format_generic_payload
        
        payload = format_generic_payload(deal, webhook.template)
        
        # Parse custom headers if provided
        headers = {}
        if webhook.headers:
            try:
                headers = json.loads(webhook.headers)
            except json.JSONDecodeError:
                pass
        
        headers.setdefault("Content-Type", "application/json")
        
        client = await self._get_client()
        response = await client.post(webhook.url, json=payload, headers=headers)
        
        success = response.status_code in (200, 201, 202, 204)
        if not success:
            logger.warning(f"Generic webhook failed: {response.status_code} - {response.text}")
        
        return success, payload
    
    async def test_webhook(
        self,
        db: AsyncSession,
        webhook: Webhook,
    ) -> tuple[bool, str]:
        """
        Test a webhook with a sample notification.
        
        Args:
            db: Database session
            webhook: Webhook to test
            
        Returns:
            Tuple of (success, message)
        """
        from src.ingest.category_scanner import DiscoveredProduct
        
        # Create test deal
        test_product = DiscoveredProduct(
            sku="TEST-SKU-123",
            title="Test Product - Webhook Test",
            url="https://example.com/test-product",
            current_price=Decimal("9.99"),
            original_price=Decimal("49.99"),
            store="test_store",
        )
        
        test_deal = DetectedDeal(
            product=test_product,
            discount_percent=80.0,
            detection_method="test",
            confidence=1.0,
            reason="This is a test notification",
            category="Test",
            detection_signals=["test"],
        )
        
        try:
            webhook_type = WebhookType(webhook.webhook_type)
            
            if webhook_type == WebhookType.DISCORD:
                success, _ = await self._send_discord(webhook, test_deal)
            elif webhook_type == WebhookType.TELEGRAM:
                success, _ = await self._send_telegram(webhook, test_deal)
            elif webhook_type == WebhookType.SLACK:
                success, _ = await self._send_slack(webhook, test_deal)
            elif webhook_type == WebhookType.GENERIC:
                success, _ = await self._send_generic(webhook, test_deal)
            else:
                return False, f"Unknown webhook type: {webhook.webhook_type}"
            
            if success:
                return True, "Test notification sent successfully"
            else:
                return False, "Webhook returned non-success status"
                
        except Exception as e:
            return False, f"Error: {str(e)}"


# Global webhook manager instance
webhook_manager = WebhookManager()
