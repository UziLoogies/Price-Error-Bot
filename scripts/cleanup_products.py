#!/usr/bin/env python3
"""
Database cleanup script for transitioning to category-based scanning.

Truncates products, price_history, and alerts tables while preserving:
- rules
- webhooks
- proxy_configs
- store_categories
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.db.session import AsyncSessionLocal


async def cleanup_products():
    """Truncate product-related tables."""
    print("Starting database cleanup...")
    
    async with AsyncSessionLocal() as db:
        # Get counts before cleanup
        result = await db.execute(text("SELECT COUNT(*) FROM products"))
        product_count = result.scalar()
        
        result = await db.execute(text("SELECT COUNT(*) FROM price_history"))
        history_count = result.scalar()
        
        result = await db.execute(text("SELECT COUNT(*) FROM alerts"))
        alert_count = result.scalar()
        
        print(f"Current counts:")
        print(f"  - Products: {product_count}")
        print(f"  - Price History: {history_count}")
        print(f"  - Alerts: {alert_count}")
        
        if product_count == 0 and history_count == 0 and alert_count == 0:
            print("\nTables are already empty. Nothing to clean up.")
            return
        
        # Confirm cleanup
        confirm = input("\nAre you sure you want to delete all product data? (yes/no): ")
        if confirm.lower() != "yes":
            print("Cleanup cancelled.")
            return
        
        # Delete in correct order due to foreign keys
        print("\nDeleting alerts...")
        await db.execute(text("DELETE FROM alerts"))
        
        print("Deleting price history...")
        await db.execute(text("DELETE FROM price_history"))
        
        print("Deleting products...")
        await db.execute(text("DELETE FROM products"))
        
        await db.commit()
        
        print("\n[OK] Cleanup complete!")
        print("  - Preserved: rules, webhooks, proxy_configs, store_categories")


async def cleanup_products_noninteractive():
    """Non-interactive version for automation."""
    print("Starting database cleanup (non-interactive)...")
    
    async with AsyncSessionLocal() as db:
        # Delete in correct order due to foreign keys
        await db.execute(text("DELETE FROM alerts"))
        await db.execute(text("DELETE FROM price_history"))
        await db.execute(text("DELETE FROM products"))
        await db.commit()
        
        print("[OK] Cleanup complete!")


if __name__ == "__main__":
    if "--yes" in sys.argv:
        asyncio.run(cleanup_products_noninteractive())
    else:
        asyncio.run(cleanup_products())
