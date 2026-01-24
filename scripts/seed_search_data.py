#!/usr/bin/env python3
"""
Comprehensive seed script for search functionality testing.

Creates realistic test data for:
- Products (diverse SKUs, titles, stores, prices)
- Price History (price changes over time)
- Alerts (triggered price alerts)
- Categories (diverse store categories)
- Exclusions (test exclusion rules)

Usage:
    python scripts/seed_search_data.py           # Seed all data
    python scripts/seed_search_data.py --clear   # Clear all data
    python scripts/seed_search_data.py --stats   # Show data stats
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
import random
import string

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text, func
from src.db.session import AsyncSessionLocal
from src.db.models import (
    Product, PriceHistory, Alert, StoreCategory, 
    Rule, Webhook, ProductExclusion, ScanJob
)

# Test data templates
STORES = [
    "amazon_us", "walmart", "bestbuy", "target", "costco", 
    "newegg", "homedepot", "lowes", "macys", "microcenter"
]

PRODUCT_CATEGORIES = {
    "Electronics": ["iPhone", "iPad", "Samsung Galaxy", "PlayStation", "Xbox", "Nintendo Switch", "AirPods", "MacBook", "Dell Laptop", "HP Printer"],
    "Home & Garden": ["KitchenAid Mixer", "Dyson Vacuum", "Ring Doorbell", "Nest Thermostat", "Weber Grill", "Instant Pot", "Roomba", "Air Fryer"],
    "Tools & Hardware": ["DeWalt Drill", "Milwaukee Saw", "Craftsman Toolbox", "Black & Decker Sander", "Makita Impact Driver", "Ryobi Kit"],
    "Clothing": ["Nike Air Max", "Adidas Ultraboost", "Levi's Jeans", "North Face Jacket", "Under Armour Shirt", "Converse Sneakers"],
    "Toys & Games": ["LEGO Creator Set", "Barbie Dreamhouse", "Hot Wheels Track", "Monopoly Board Game", "Pokemon Cards", "Nerf Blaster"],
    "Sports": ["Wilson Basketball", "Spalding Football", "Callaway Golf Set", "Trek Bike", "Yeti Cooler", "Coleman Tent"]
}

BRANDS = ["Apple", "Samsung", "Sony", "LG", "HP", "Dell", "Nike", "Adidas", "KitchenAid", "Dyson", "LEGO", "Nintendo"]

def generate_sku(store: str, category: str) -> str:
    """Generate realistic SKU based on store and category."""
    if store == "amazon_us":
        return f"B0{random.randint(10,99)}{random.choice(string.ascii_uppercase)}{random.randint(1000,9999)}"
    elif store == "walmart":
        return f"{random.randint(100000000,999999999)}"
    elif store == "bestbuy":
        return f"{random.randint(1000000,9999999)}"
    else:
        return f"{store.upper()[:3]}{random.randint(100000,999999)}"

def generate_product_title(category: str, products: list) -> str:
    """Generate realistic product title."""
    base_product = random.choice(products)
    variants = [
        f"{base_product} Pro", f"{base_product} Max", f"{base_product} Plus",
        f"{base_product} 2023", f"{base_product} V2", f"{base_product} XL",
        f"Renewed {base_product}", f"{base_product} Bundle", f"{base_product} Kit"
    ]
    
    colors = ["Black", "White", "Silver", "Blue", "Red", "Gold", "Space Gray"]
    sizes = ["Small", "Medium", "Large", "32GB", "64GB", "128GB", "256GB", "512GB"]
    
    title = random.choice([base_product] + variants)
    
    # Add color/size modifiers randomly
    if random.random() < 0.4:
        title += f", {random.choice(colors)}"
    if random.random() < 0.3:
        title += f" - {random.choice(sizes)}"
    
    return title

def generate_price() -> Decimal:
    """Generate realistic price."""
    price_ranges = [
        (9.99, 49.99),    # Low-end items
        (50.00, 199.99),  # Mid-range items  
        (200.00, 999.99), # High-end items
        (1000.00, 4999.99) # Premium items
    ]
    
    min_price, max_price = random.choice(price_ranges)
    price = random.uniform(min_price, max_price)
    return Decimal(str(round(price, 2)))

async def clear_all_data():
    """Clear all existing data for fresh seeding."""
    print("Clearing existing data...")
    async with AsyncSessionLocal() as db:
        # Clear in dependency order
        await db.execute(text("DELETE FROM alerts"))
        await db.execute(text("DELETE FROM price_history"))
        await db.execute(text("DELETE FROM products"))
        await db.execute(text("DELETE FROM product_exclusions"))
        await db.execute(text("DELETE FROM scan_jobs"))
        await db.execute(text("DELETE FROM store_categories"))
        await db.execute(text("DELETE FROM rules"))
        await db.execute(text("DELETE FROM webhooks"))
        await db.commit()
        print("✅ All data cleared")

async def seed_rules():
    """Create basic detection rules."""
    print("Seeding detection rules...")
    async with AsyncSessionLocal() as db:
        rules = [
            Rule(name="High Discount", rule_type="percentage", threshold=Decimal("50.0"), enabled=True, priority=1),
            Rule(name="Price Drop", rule_type="absolute", threshold=Decimal("100.0"), enabled=True, priority=2),
            Rule(name="MSRP Below 60%", rule_type="msrp_ratio", threshold=Decimal("0.6"), enabled=True, priority=3),
        ]
        
        for rule in rules:
            db.add(rule)
        
        await db.commit()
        print(f"✅ Created {len(rules)} detection rules")

async def seed_webhooks():
    """Create test webhook configurations."""
    print("Seeding webhooks...")
    async with AsyncSessionLocal() as db:
        webhooks = [
            Webhook(name="Test Discord", url="https://discord.com/api/webhooks/test", enabled=True),
            Webhook(name="Backup Discord", url="https://discord.com/api/webhooks/backup", enabled=False),
        ]
        
        for webhook in webhooks:
            db.add(webhook)
        
        await db.commit()
        print(f"✅ Created {len(webhooks)} webhooks")

async def seed_products():
    """Create diverse test products for search testing."""
    print("Seeding products...")
    async with AsyncSessionLocal() as db:
        products = []
        product_id = 1
        
        for store in STORES:
            for category, product_list in PRODUCT_CATEGORIES.items():
                # Create 3-8 products per category per store
                num_products = random.randint(3, 8)
                for _ in range(num_products):
                    sku = generate_sku(store, category)
                    title = generate_product_title(category, product_list)
                    msrp = generate_price()
                    baseline_price = msrp * Decimal(str(random.uniform(0.7, 0.95)))  # Usually below MSRP
                    
                    product = Product(
                        sku=sku,
                        store=store,
                        title=title,
                        url=f"https://{store}.com/product/{sku}",
                        msrp=msrp,
                        baseline_price=baseline_price,
                        created_at=datetime.utcnow() - timedelta(days=random.randint(1, 365))
                    )
                    products.append(product)
                    db.add(product)
                    
                    # Add periodic commit to avoid memory issues
                    if len(products) % 100 == 0:
                        await db.commit()
        
        await db.commit()
        print(f"✅ Created {len(products)} products across {len(STORES)} stores")
        return products

async def seed_price_history(products: list):
    """Create price history for products."""
    print("Seeding price history...")
    async with AsyncSessionLocal() as db:
        total_history = 0
        
        for product in products[:200]:  # Limit to first 200 products for performance
            # Create 5-15 price points over time
            num_points = random.randint(5, 15)
            base_price = product.baseline_price
            
            for i in range(num_points):
                # Generate price with some volatility
                price_multiplier = random.uniform(0.8, 1.3)
                price = base_price * Decimal(str(price_multiplier))
                
                # Generate historical timestamp
                days_ago = random.randint(1, 90)
                fetched_at = datetime.utcnow() - timedelta(days=days_ago)
                
                price_history = PriceHistory(
                    product_id=product.id,
                    price=price,
                    original_price=price * Decimal(str(random.uniform(1.1, 1.5))) if random.random() < 0.3 else None,
                    shipping=Decimal(str(random.uniform(0, 15.99))),
                    availability=random.choice(["In Stock", "Limited Stock", "Out of Stock", "Pre-order"]),
                    confidence=random.uniform(0.8, 1.0),
                    fetched_at=fetched_at
                )
                
                db.add(price_history)
                total_history += 1
                
                # Periodic commit
                if total_history % 500 == 0:
                    await db.commit()
        
        await db.commit()
        print(f"✅ Created {total_history} price history records")

async def seed_alerts(products: list):
    """Create test alerts for products."""
    print("Seeding alerts...")
    async with AsyncSessionLocal() as db:
        # Get rules for alert creation
        rules_result = await db.execute(select(Rule))
        rules = rules_result.scalars().all()
        
        if not rules:
            print("⚠️ No rules found, skipping alerts")
            return
        
        alerts = []
        
        # Create alerts for random products (about 20% of products)
        sample_products = random.sample(products[:100], min(20, len(products)))
        
        for product in sample_products:
            # Create 1-3 alerts per product
            num_alerts = random.randint(1, 3)
            
            for _ in range(num_alerts):
                rule = random.choice(rules)
                triggered_price = product.baseline_price * Decimal(str(random.uniform(0.4, 0.8)))
                previous_price = product.baseline_price
                
                alert = Alert(
                    product_id=product.id,
                    rule_id=rule.id,
                    triggered_price=triggered_price,
                    previous_price=previous_price,
                    discord_message_id=f"msg_{random.randint(100000, 999999)}",
                    sent_at=datetime.utcnow() - timedelta(days=random.randint(1, 30))
                )
                
                alerts.append(alert)
                db.add(alert)
        
        await db.commit()
        print(f"✅ Created {len(alerts)} alerts")

async def seed_exclusions():
    """Create product exclusions for testing."""
    print("Seeding exclusions...")
    async with AsyncSessionLocal() as db:
        exclusions = [
            ProductExclusion(store="amazon_us", keyword="refurbished", reason="Exclude refurbished items", enabled=True),
            ProductExclusion(store="walmart", keyword="clearance", reason="Exclude clearance items", enabled=True),
            ProductExclusion(store="bestbuy", sku="123456789", reason="Specific SKU exclusion", enabled=True),
            ProductExclusion(store="target", brand="Generic Brand", reason="Low quality brand", enabled=True),
            ProductExclusion(store="newegg", keyword="open box", reason="Exclude open box items", enabled=False),
        ]
        
        for exclusion in exclusions:
            db.add(exclusion)
        
        await db.commit()
        print(f"✅ Created {len(exclusions)} exclusions")

async def seed_scan_jobs():
    """Create test scan job history."""
    print("Seeding scan jobs...")
    async with AsyncSessionLocal() as db:
        # Get categories for job references
        categories_result = await db.execute(select(StoreCategory))
        categories = categories_result.scalars().all()
        
        jobs = []
        
        for i in range(30):  # Create 30 job records
            status = random.choice(["completed", "completed", "completed", "failed", "running"])
            job_type = random.choice(["category", "manual", "scheduled"])
            
            started_at = datetime.utcnow() - timedelta(hours=random.randint(1, 48))
            completed_at = started_at + timedelta(minutes=random.randint(5, 120)) if status in ["completed", "failed"] else None
            
            total_items = random.randint(50, 500)
            processed_items = total_items if status == "completed" else random.randint(0, total_items)
            success_count = random.randint(0, processed_items) if status == "completed" else random.randint(0, processed_items // 2)
            error_count = processed_items - success_count
            
            job = ScanJob(
                job_type=job_type,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                total_items=total_items,
                processed_items=processed_items,
                success_count=success_count,
                error_count=error_count,
                products_found=random.randint(0, success_count),
                deals_found=random.randint(0, success_count // 3),
                category_id=random.choice(categories).id if categories and random.random() < 0.7 else None,
                error_message="Network timeout during scan" if status == "failed" else None,
                created_at=started_at - timedelta(minutes=5)
            )
            
            jobs.append(job)
            db.add(job)
        
        await db.commit()
        print(f"✅ Created {len(jobs)} scan jobs")

async def show_data_stats():
    """Show statistics about seeded data."""
    print("\n📊 Database Statistics:")
    print("=" * 50)
    
    async with AsyncSessionLocal() as db:
        # Product stats
        product_count = await db.execute(select(func.count(Product.id)))
        product_total = product_count.scalar()
        
        store_breakdown = await db.execute(
            select(Product.store, func.count(Product.id)).group_by(Product.store)
        )
        
        print(f"Products: {product_total} total")
        for store, count in store_breakdown.all():
            print(f"  - {store}: {count}")
        
        # Price history stats
        history_count = await db.execute(select(func.count(PriceHistory.id)))
        history_total = history_count.scalar()
        print(f"Price History: {history_total} records")
        
        # Alert stats  
        alert_count = await db.execute(select(func.count(Alert.id)))
        alert_total = alert_count.scalar()
        print(f"Alerts: {alert_total} records")
        
        # Category stats
        category_count = await db.execute(select(func.count(StoreCategory.id)))
        category_total = category_count.scalar()
        print(f"Categories: {category_total} records")
        
        # Scan job stats
        job_count = await db.execute(select(func.count(ScanJob.id)))
        job_total = job_count.scalar()
        print(f"Scan Jobs: {job_total} records")
        
        # Exclusion stats
        exclusion_count = await db.execute(select(func.count(ProductExclusion.id)))
        exclusion_total = exclusion_count.scalar()
        print(f"Exclusions: {exclusion_total} records")

async def seed_all_data():
    """Seed all test data for search functionality."""
    print("🌱 Seeding comprehensive search test data...")
    print("=" * 50)
    
    await seed_rules()
    await seed_webhooks()
    
    # Seed categories first (from existing seed script)
    print("Seeding categories (using existing script)...")
    from scripts.seed_categories import seed_categories
    await seed_categories()
    
    # Then seed products and related data
    products = await seed_products()
    await seed_price_history(products)
    await seed_alerts(products)
    await seed_exclusions()
    await seed_scan_jobs()
    
    print("\n🎉 Seeding complete!")
    await show_data_stats()

async def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        if sys.argv[1] == "--clear":
            await clear_all_data()
        elif sys.argv[1] == "--stats":
            await show_data_stats()
        elif sys.argv[1] == "--help":
            print(__doc__)
        else:
            print(f"Unknown option: {sys.argv[1]}")
            print("Use --help for usage information")
    else:
        await seed_all_data()

if __name__ == "__main__":
    asyncio.run(main())