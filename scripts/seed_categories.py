#!/usr/bin/env python3
"""
Category seeding script for initializing store categories.

Loads categories from categories_seed.json and populates the store_categories table.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from src.db.session import AsyncSessionLocal
from src.db.models import StoreCategory


async def seed_categories():
    """Seed store categories from JSON file."""
    seed_file = Path(__file__).parent.parent / "categories_seed.json"
    
    if not seed_file.exists():
        print(f"Error: {seed_file} not found")
        return
    
    with open(seed_file, "r") as f:
        data = json.load(f)
    
    categories = data.get("categories", [])
    
    if not categories:
        print("No categories found in seed file")
        return
    
    print(f"Found {len(categories)} categories to seed...")
    
    async with AsyncSessionLocal() as db:
        added = 0
        skipped = 0
        
        for cat in categories:
            # Check if category already exists
            query = select(StoreCategory).where(
                StoreCategory.store == cat["store"],
                StoreCategory.category_url == cat["category_url"]
            )
            result = await db.execute(query)
            existing = result.scalar_one_or_none()
            
            if existing:
                print(f"  [SKIP] {cat['store']}: {cat['category_name']} (already exists)")
                skipped += 1
                continue
            
            # Create new category
            new_category = StoreCategory(
                store=cat["store"],
                category_name=cat["category_name"],
                category_url=cat["category_url"],
                enabled=True,
                max_pages=cat.get("max_pages", 3),
                scan_interval_minutes=cat.get("scan_interval_minutes", 30),
                priority=cat.get("priority", 5),
                min_discount_percent=cat.get("min_discount_percent", 50.0),
            )
            
            db.add(new_category)
            print(f"  [ADD] {cat['store']}: {cat['category_name']}")
            added += 1
        
        await db.commit()
        
        print(f"\nSeeding complete!")
        print(f"  - Added: {added}")
        print(f"  - Skipped: {skipped}")


async def list_categories():
    """List all stored categories."""
    async with AsyncSessionLocal() as db:
        query = select(StoreCategory).order_by(StoreCategory.store, StoreCategory.priority.desc())
        result = await db.execute(query)
        categories = result.scalars().all()
        
        if not categories:
            print("No categories found.")
            return
        
        print(f"\nStored Categories ({len(categories)} total):\n")
        
        current_store = None
        for cat in categories:
            if cat.store != current_store:
                current_store = cat.store
                print(f"\n{current_store.upper()}")
                print("-" * 40)
            
            status = "[ON]" if cat.enabled else "[OFF]"
            print(f"  {status} {cat.category_name} (P{cat.priority}, {cat.max_pages}pg, {cat.min_discount_percent}%)")


async def clear_categories():
    """Clear all categories."""
    async with AsyncSessionLocal() as db:
        from sqlalchemy import text
        await db.execute(text("DELETE FROM store_categories"))
        await db.commit()
        print("All categories cleared.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--list":
            asyncio.run(list_categories())
        elif sys.argv[1] == "--clear":
            asyncio.run(clear_categories())
        elif sys.argv[1] == "--help":
            print("Usage: python seed_categories.py [OPTIONS]")
            print("")
            print("Options:")
            print("  --list   List all stored categories")
            print("  --clear  Clear all categories")
            print("  --help   Show this help message")
            print("")
            print("With no options, seeds categories from categories_seed.json")
        else:
            print(f"Unknown option: {sys.argv[1]}")
    else:
        asyncio.run(seed_categories())
