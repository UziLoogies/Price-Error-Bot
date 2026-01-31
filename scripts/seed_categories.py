#!/usr/bin/env python3
"""
Category seeding script for initializing store categories.

Loads categories from categories_seed.json and populates the store_categories table.

Schema for categories_seed.json:
- Each category object must have: store, category_name, category_url, enabled
- Required fields:
  - enabled: bool (REQUIRED) - Whether the category is enabled for scanning.
    All entries must have this field explicitly set to true or false for consistency.
- Optional fields with defaults:
  - max_pages: int (default: 3) - Maximum pages to scan
  - scan_interval_minutes: int (default: 30) - Minutes between scans
  - priority: int (default: 5) - Scan priority (higher = scanned first)
  - min_discount_percent: float (default: 50.0) - Minimum discount to consider
  - keywords, exclude_keywords, brands: Optional JSON array strings
  - min_price, max_price, msrp_threshold: Optional floats

Note: The "enabled" field is required and must be explicitly set in every category object.
Missing "enabled" will cause the category to be skipped with an error.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from sqlalchemy import select
from src.db.session import AsyncSessionLocal
from src.db.models import StoreCategory


async def validate_url(url: str, timeout: float = 10.0) -> tuple[bool, str]:
    """
    Validate that a URL is accessible.
    
    Returns:
        (is_valid, error_message)
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return False, "404 Not Found"
            elif response.status_code >= 400:
                return False, f"HTTP {response.status_code}"
            return True, ""
    except httpx.TimeoutException:
        return False, "Timeout"
    except httpx.ConnectError:
        return False, "Connection error"
    except Exception as e:
        return False, str(e)


async def seed_categories(validate_urls: bool = False):
    """Seed store categories from JSON file.
    
    Args:
        validate_urls: If True, validate URLs before seeding (slower but catches stale URLs)
    """
    seed_file = Path(__file__).parent.parent / "categories_seed.json"
    
    if not seed_file.exists():
        print(f"Error: {seed_file} not found")
        sys.exit(1)
    
    try:
        with open(seed_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {seed_file}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to read {seed_file}: {e}")
        sys.exit(1)
    
    categories = data.get("categories", [])
    
    if not categories:
        print("No categories found in seed file")
        return
    
    print(f"Found {len(categories)} categories to seed...")
    
    try:
        async with AsyncSessionLocal() as db:
            added = 0
            skipped = 0
            errors = 0
            
            for idx, cat in enumerate(categories, 1):
                try:
                    # Validate required fields
                    required_fields = ["store", "category_name", "category_url", "enabled"]
                    missing_fields = [field for field in required_fields if field not in cat]
                    if missing_fields:
                        print(f"  [ERROR] Category {idx}: Missing required fields: {', '.join(missing_fields)}")
                        errors += 1
                        continue
                    
                    # Validate enabled field type
                    if not isinstance(cat.get("enabled"), bool):
                        print(f"  [ERROR] Category {idx}: 'enabled' field must be a boolean (true or false)")
                        errors += 1
                        continue
                    
                    # Optional URL validation
                    if validate_urls:
                        url = cat["category_url"]
                        is_valid, error_msg = await validate_url(url)
                        if not is_valid:
                            print(f"  [WARN] Category {idx}: URL validation failed: {error_msg}")
                            print(f"         URL: {url}")
                            response = input("         Continue anyway? (y/N): ")
                            if response.lower() != 'y':
                                print(f"  [SKIP] {cat['store']}: {cat['category_name']} (URL validation failed)")
                                skipped += 1
                                continue
                    
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
                    # Note: enabled is required and validated above - all entries must have "enabled" explicitly set
                    new_category = StoreCategory(
                        store=cat["store"],
                        category_name=cat["category_name"],
                        category_url=cat["category_url"],
                        enabled=cat["enabled"],  # Required field, validated above
                        max_pages=cat.get("max_pages", 3),
                        scan_interval_minutes=cat.get("scan_interval_minutes", 30),
                        priority=cat.get("priority", 5),
                        min_discount_percent=cat.get("min_discount_percent", 50.0),
                    )
                    
                    db.add(new_category)
                    print(f"  [ADD] {cat['store']}: {cat['category_name']}")
                    added += 1
                    
                except Exception as e:
                    print(f"  [ERROR] Category {idx} ({cat.get('store', 'unknown')}): {e}")
                    errors += 1
                    continue
            
            try:
                await db.commit()
            except Exception as e:
                print(f"\nError: Failed to commit changes to database: {e}")
                await db.rollback()
                sys.exit(1)
            
            print(f"\nSeeding complete!")
            print(f"  - Added: {added}")
            print(f"  - Skipped: {skipped}")
            if errors > 0:
                print(f"  - Errors: {errors}")
                
    except Exception as e:
        print(f"\nError: Database connection failed: {e}")
        print("Make sure Docker containers are running and database is accessible.")
        sys.exit(1)


async def list_categories():
    """List all stored categories."""
    try:
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
    except Exception as e:
        print(f"Error: Failed to list categories: {e}")
        print("Make sure Docker containers are running and database is accessible.")
        sys.exit(1)


async def clear_categories():
    """Clear all categories."""
    try:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import text
            await db.execute(text("DELETE FROM store_categories"))
            await db.commit()
            print("All categories cleared.")
    except Exception as e:
        print(f"Error: Failed to clear categories: {e}")
        print("Make sure Docker containers are running and database is accessible.")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--list":
            asyncio.run(list_categories())
        elif sys.argv[1] == "--clear":
            asyncio.run(clear_categories())
        elif sys.argv[1] == "--validate":
            asyncio.run(seed_categories(validate_urls=True))
        elif sys.argv[1] == "--help":
            print("Usage: python seed_categories.py [OPTIONS]")
            print("")
            print("Options:")
            print("  --list      List all stored categories")
            print("  --clear     Clear all categories")
            print("  --validate  Validate URLs before seeding (interactive)")
            print("  --help      Show this help message")
            print("")
            print("With no options, seeds categories from categories_seed.json")
        else:
            print(f"Unknown option: {sys.argv[1]}")
    else:
        asyncio.run(seed_categories())
