"""Discord webhook integration for price alerts."""

import logging
import time
from datetime import datetime
from decimal import Decimal

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class GrafanaAnnotations:
    """Push annotations to Grafana for timeline visualization."""

    def __init__(
        self,
        grafana_url: str = "http://localhost:3000",
        api_key: str | None = None,
    ):
        self.grafana_url = grafana_url.rstrip("/")
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            else:
                # Use basic auth for local development
                headers["Authorization"] = "Basic YWRtaW46YWRtaW4="  # admin:admin
            self._client = httpx.AsyncClient(timeout=10.0, headers=headers)
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def push_alert_annotation(
        self,
        sku: str,
        store: str,
        current_price: Decimal,
        reason: str,
        product_title: str | None = None,
        dashboard_uid: str = "price-bot-overview",
    ) -> bool:
        """
        Push an annotation to Grafana.

        Args:
            sku: Product SKU
            store: Store name
            current_price: Current price
            reason: Alert reason
            product_title: Product title
            dashboard_uid: Dashboard UID to attach annotation to

        Returns:
            True if successful, False otherwise
        """
        try:
            client = await self._get_client()

            annotation = {
                "dashboardUID": dashboard_uid,
                "time": int(time.time() * 1000),  # milliseconds
                "tags": ["price-alert", store, f"sku:{sku}"],
                "text": f"<b>{product_title or sku}</b><br>"
                        f"Price: ${current_price:.2f}<br>"
                        f"Reason: {reason}",
            }

            response = await client.post(
                f"{self.grafana_url}/api/annotations",
                json=annotation,
            )

            if response.status_code in (200, 201):
                logger.debug(f"Pushed Grafana annotation for {sku}")
                return True
            else:
                logger.warning(
                    f"Failed to push Grafana annotation: {response.status_code}"
                )
                return False

        except Exception as e:
            # Don't fail the alert if Grafana annotation fails
            logger.debug(f"Grafana annotation failed (non-critical): {e}")
            return False


# Global annotations client
grafana_annotations = GrafanaAnnotations()


class DiscordWebhook:
    """Discord webhook client for sending price alerts."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self._http_client: httpx.AsyncClient | None = None

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

    async def send_price_alert(
        self,
        product_title: str | None,
        product_url: str,
        sku: str,
        store: str,
        current_price: Decimal,
        previous_price: Decimal | None,
        baseline_price: Decimal | None,
        msrp: Decimal | None,
        reason: str,
        confidence: float = 1.0,
        image_url: str | None = None,
    ) -> str | None:
        """
        Send a price drop alert to Discord.

        Args:
            product_title: Product title
            product_url: Product URL
            sku: Product SKU/ASIN
            store: Store name
            current_price: Current price
            previous_price: Previous price (if available)
            baseline_price: Baseline price (if available)
            msrp: MSRP (if available)
            reason: Reason for alert
            confidence: Confidence score (0.0-1.0)
            image_url: Product image URL (optional)

        Returns:
            Discord message ID if successful, None otherwise
        """
        client = await self._get_client()

        # Calculate drop percentage
        drop_percent = None
        if previous_price and previous_price > 0:
            drop_percent = ((previous_price - current_price) / previous_price) * 100
        elif baseline_price and baseline_price > 0:
            drop_percent = ((baseline_price - current_price) / baseline_price) * 100

        # Build embed
        embed = {
            "title": f"💰 Price Drop Alert: {product_title or 'Product'}",
            "url": product_url,
            "color": 0x00FF00 if confidence >= 0.7 else 0xFFA500,  # Green or Orange
            "fields": [
                {
                    "name": "Current Price",
                    "value": f"${current_price:.2f}",
                    "inline": True,
                },
            ],
            "footer": {"text": f"SKU: {sku} | {store}"},
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Add previous price if available
        if previous_price:
            embed["fields"].append(
                {
                    "name": "Was",
                    "value": f"${previous_price:.2f}",
                    "inline": True,
                }
            )

        # Add drop percentage
        if drop_percent:
            embed["fields"].append(
                {
                    "name": "Drop",
                    "value": f"{drop_percent:.1f}%",
                    "inline": True,
                }
            )

        # Add reason
        embed["fields"].append(
            {
                "name": "Reason",
                "value": reason,
                "inline": False,
            }
        )

        # Add confidence indicator
        if confidence < 0.7:
            embed["fields"].append(
                {
                    "name": "⚠️ Confidence",
                    "value": f"{confidence * 100:.0f}% (low confidence)",
                    "inline": False,
                }
            )

        # Add product image if available
        if image_url:
            embed["image"] = {
                "url": image_url,
            }

        # Build webhook payload
        payload = {
            "embeds": [embed],
            "username": "Price Error Bot",
        }

        try:
            response = await client.post(self.webhook_url, json=payload)
            response.raise_for_status()

            data = response.json()
            message_id = data.get("id") or str(data.get("message_id", ""))

            logger.info(f"Sent Discord alert for {sku}: {reason}")

            # Also push annotation to Grafana (non-blocking, best-effort)
            try:
                await grafana_annotations.push_alert_annotation(
                    sku=sku,
                    store=store,
                    current_price=current_price,
                    reason=reason,
                    product_title=product_title,
                )
            except Exception as annotation_error:
                logger.debug(f"Grafana annotation failed: {annotation_error}")

            return message_id

        except Exception as e:
            logger.error(f"Failed to send Discord alert for {sku}: {e}")
            raise
