"""APScheduler job definitions with time-based optimization."""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.worker.tasks import task_runner
from src.worker.baseline_job import run_baseline_aggregation
from src.detect.ml_trainer import train_isolation_forest

logger = logging.getLogger(__name__)


def is_sale_period() -> bool:
    """
    Check if current time is during a known sale period.
    
    Returns:
        True if during sale period
    """
    now = datetime.utcnow()
    month = now.month
    day = now.day
    
    # Black Friday (4th Thursday of November)
    if month == 11 and 23 <= day <= 29:
        return True
    
    # Cyber Monday (Monday after Black Friday)
    if month == 11 and day == 30:
        return True
    
    # Prime Day (typically July, but varies)
    if month == 7 and 10 <= day <= 16:
        return True
    
    # Holiday season (Nov-Dec)
    if month in [11, 12]:
        return True
    
    # Post-holiday clearance (Jan)
    if month == 1 and day <= 7:
        return True
    
    return False


def get_scan_interval_multiplier() -> float:
    """
    Get scan interval multiplier based on time of day and sale periods.
    
    Returns:
        Multiplier (0.5-1.5, lower = scan more frequently)
    """
    now = datetime.utcnow()
    hour = now.hour
    
    # During sale periods, scan more frequently
    if is_sale_period():
        return 0.5  # Scan twice as often
    
    # Nightly sync windows (midnight-2 AM) - scan more frequently
    if 0 <= hour < 2:
        return 0.7  # Scan more often during sync windows
    
    # Weekend - slightly more frequent (more deals)
    if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return 0.9
    
    return 1.0  # Normal frequency


def setup_scheduler() -> AsyncIOScheduler:
    """
    Setup and configure APScheduler.
    
    Category-first scanning approach:
    - Scans store category pages every 5 minutes to discover deals
    - No individual product tracking - all discovery via categories

    Returns:
        Configured scheduler instance
    """
    scheduler = AsyncIOScheduler()

    # Category scanning job - run every 5 minutes for active deal discovery
    scheduler.add_job(
        task_runner.scan_store_categories,
        IntervalTrigger(minutes=5),
        id="category_scan",
        name="Scan store categories for deals",
        max_instances=2,
        coalesce=True,
        misfire_grace_time=300,
        replace_existing=True,
    )

    # Daily baseline recalculation - run at 3 AM (for any discovered products)
    scheduler.add_job(
        task_runner.recalculate_baselines,
        CronTrigger(hour=3, minute=0),
        id="baseline_recalc",
        name="Recalculate baseline prices",
        max_instances=1,
        replace_existing=True,
    )
    
    # Baseline aggregation job - run every 6 hours
    scheduler.add_job(
        run_baseline_aggregation,
        IntervalTrigger(hours=6),
        id="baseline_aggregation",
        name="Aggregate price history into baseline cache",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    
    # ML model training - run weekly on Sundays at 4 AM
    scheduler.add_job(
        train_isolation_forest,
        CronTrigger(day_of_week="sun", hour=4, minute=0),
        id="ml_training",
        name="Train Isolation Forest anomaly detection model",
        max_instances=1,
        replace_existing=True,
    )

    logger.info(
        "Scheduler configured: category scan every 5 minutes, "
        "baseline recalculation at 3 AM, baseline aggregation every 6 hours, "
        "ML training on Sundays at 4 AM"
    )

    return scheduler
