"""Platform-specific message formatters for webhook notifications.

Provides formatters for:
- Discord (embed format)
- Telegram (Markdown)
- Slack (Block Kit)
- Generic (JSON)
"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

from src.detect.deal_detector import DetectedDeal


def format_discord_embed(
    deal: DetectedDeal,
    custom_template: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Format deal as Discord embed.
    
    Args:
        deal: Detected deal
        custom_template: Optional custom template (JSON)
        
    Returns:
        Discord webhook payload
    """
    product = deal.product
    
    # Determine color based on discount/confidence
    if deal.discount_percent >= 70:
        color = 0xFF0000  # Red for extreme deals
    elif deal.discount_percent >= 50:
        color = 0x00FF00  # Green for great deals
    else:
        color = 0xFFA500  # Orange for good deals
    
    # Build fields
    fields = [
        {
            "name": "Current Price",
            "value": f"${product.current_price:.2f}",
            "inline": True,
        },
    ]
    
    if product.original_price:
        fields.append({
            "name": "Was",
            "value": f"${product.original_price:.2f}",
            "inline": True,
        })
    
    fields.append({
        "name": "Discount",
        "value": f"{deal.discount_percent:.1f}% OFF",
        "inline": True,
    })
    
    fields.append({
        "name": "Confidence",
        "value": f"{deal.confidence * 100:.0f}%",
        "inline": True,
    })
    
    if deal.reason:
        fields.append({
            "name": "Reason",
            "value": deal.reason[:1024],
            "inline": False,
        })
    
    if deal.detection_signals:
        fields.append({
            "name": "Detection Methods",
            "value": ", ".join(deal.detection_signals),
            "inline": False,
        })
    
    # Build embed
    embed = {
        "title": f"💰 {deal.discount_percent:.0f}% OFF: {product.title or 'Product Deal'}",
        "url": product.url,
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"SKU: {product.sku} | {product.store}",
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    # Add thumbnail if image available
    if product.image_url:
        embed["thumbnail"] = {"url": product.image_url}
    
    # Check if it's likely a price error
    if deal.is_price_error:
        embed["title"] = f"🔥 PRICE ERROR? {embed['title']}"
    
    payload = {
        "embeds": [embed],
        "username": "Price Error Bot",
    }
    
    return payload


def format_telegram_message(
    deal: DetectedDeal,
    custom_template: Optional[str] = None,
) -> str:
    """
    Format deal as Telegram Markdown message.
    
    Args:
        deal: Detected deal
        custom_template: Optional custom template
        
    Returns:
        Telegram message string
    """
    product = deal.product
    
    # Build message
    emoji = "🔥" if deal.is_price_error else "💰"
    
    lines = [
        f"{emoji} *{deal.discount_percent:.0f}% OFF*",
        "",
        f"*{_escape_markdown(product.title or 'Product')}*",
        "",
        f"💵 Current: *${product.current_price:.2f}*",
    ]
    
    if product.original_price:
        lines.append(f"~~Was: ${product.original_price:.2f}~~")
    
    lines.extend([
        "",
        f"🏪 Store: {product.store}",
        f"📦 SKU: `{product.sku}`",
        f"📊 Confidence: {deal.confidence * 100:.0f}%",
    ])
    
    if deal.reason:
        lines.extend(["", f"ℹ️ {_escape_markdown(deal.reason[:200])}"])
    
    lines.extend([
        "",
        f"[🔗 View Deal]({product.url})",
    ])
    
    return "\n".join(lines)


def _escape_markdown(text: str) -> str:
    """Escape Telegram Markdown special characters."""
    chars_to_escape = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in chars_to_escape:
        text = text.replace(char, f'\\{char}')
    return text


def format_slack_blocks(
    deal: DetectedDeal,
    custom_template: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Format deal as Slack Block Kit message.
    
    Args:
        deal: Detected deal
        custom_template: Optional custom template
        
    Returns:
        Slack webhook payload
    """
    product = deal.product
    
    emoji = ":fire:" if deal.is_price_error else ":moneybag:"
    
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{deal.discount_percent:.0f}% OFF - {product.title or 'Product Deal'}"[:150],
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Current Price:*\n${product.current_price:.2f}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Discount:*\n{deal.discount_percent:.1f}%",
                },
            ],
        },
    ]
    
    if product.original_price:
        blocks.append({
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Was:*\n~${product.original_price:.2f}~",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Confidence:*\n{deal.confidence * 100:.0f}%",
                },
            ],
        })
    
    if deal.reason:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Reason:* {deal.reason[:500]}",
            },
        })
    
    # Add store/SKU context
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f":package: SKU: `{product.sku}` | :department_store: {product.store}",
            },
        ],
    })
    
    # Add action button
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "View Deal",
                    "emoji": True,
                },
                "url": product.url,
                "style": "primary",
            },
        ],
    })
    
    return {"blocks": blocks}


def format_generic_payload(
    deal: DetectedDeal,
    custom_template: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Format deal as generic JSON payload.
    
    Args:
        deal: Detected deal
        custom_template: Optional Jinja2 template
        
    Returns:
        JSON payload dict
    """
    product = deal.product
    
    payload = {
        "type": "price_alert",
        "timestamp": datetime.utcnow().isoformat(),
        "deal": {
            "discount_percent": deal.discount_percent,
            "confidence": deal.confidence,
            "detection_method": deal.detection_method,
            "is_price_error": deal.is_price_error,
            "reason": deal.reason,
            "category": deal.category,
            "signals": deal.detection_signals,
        },
        "product": {
            "sku": product.sku,
            "store": product.store,
            "title": product.title,
            "url": product.url,
            "current_price": float(product.current_price) if product.current_price else None,
            "original_price": float(product.original_price) if product.original_price else None,
            "image_url": product.image_url,
        },
    }
    
    # If custom template is valid JSON, merge with payload
    if custom_template:
        try:
            template_data = json.loads(custom_template)
            # Allow template to override/extend payload
            if isinstance(template_data, dict):
                payload.update(template_data)
        except json.JSONDecodeError:
            pass
    
    return payload


def format_for_type(
    webhook_type: str,
    deal: DetectedDeal,
    custom_template: Optional[str] = None,
) -> Any:
    """
    Format deal for a specific webhook type.
    
    Args:
        webhook_type: Type of webhook (discord, telegram, slack, generic)
        deal: Detected deal
        custom_template: Optional custom template
        
    Returns:
        Formatted payload/message
    """
    formatters = {
        "discord": format_discord_embed,
        "telegram": format_telegram_message,
        "slack": format_slack_blocks,
        "generic": format_generic_payload,
    }
    
    formatter = formatters.get(webhook_type.lower(), format_generic_payload)
    return formatter(deal, custom_template)
