"""APScheduler job definitions with time-based optimization."""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.worker.tasks import task_runner
from src.worker.baseline_job import run_baseline_aggregation
from src.worker.scan_watchdog import scan_watchdog_check
from src.detect.ml_trainer import train_isolation_forest
from src.config import settings

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
    
    Scheduling overview:
    - Category scans run at settings.fetch_interval_minutes when scan_mode includes category
    - Signal scans run at settings.signal_ingest_interval_minutes when scan_mode includes signal

    Returns:
        Configured scheduler instance
    """
    scheduler = AsyncIOScheduler()
    scan_mode = getattr(settings, "scan_mode", "category").lower()
    scan_interval = max(1, int(getattr(settings, "fetch_interval_minutes", 5)))
    signal_interval = max(1, int(getattr(settings, "signal_ingest_interval_minutes", 10)))

    if scan_mode in ("category", "hybrid"):
        # Category scanning job - run at configured interval for active deal discovery
        scheduler.add_job(
            task_runner.scan_store_categories,
            IntervalTrigger(minutes=scan_interval),
            id="category_scan",
            name="Scan store categories for deals",
            max_instances=1,  # Prevent overlapping runs
            coalesce=True,
            misfire_grace_time=600,  # Increased from 300 to 600 seconds
            replace_existing=True,
        )

    if scan_mode in ("signal", "hybrid") and settings.third_party_enabled:
        scheduler.add_job(
            task_runner.scan_signal_sources,
            IntervalTrigger(minutes=signal_interval),
            id="signal_scan",
            name="Ingest third-party signals",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
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
    
    # Scan watchdog - run every 2 minutes to detect stale locks
    scheduler.add_job(
        scan_watchdog_check,
        IntervalTrigger(seconds=settings.scan_watchdog_interval_seconds),
        id="scan_watchdog",
        name="Scan lock watchdog",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    category_desc = (
        f"category scan every {scan_interval} minutes"
        if scan_mode in ("category", "hybrid")
        else "category scan disabled"
    )
    signal_desc = (
        f"signal scan every {signal_interval} minutes"
        if scan_mode in ("signal", "hybrid") and settings.third_party_enabled
        else "signal scan disabled"
    )

    logger.info(
        "Scheduler configured: scan_mode=%s, %s, %s, baseline recalculation at 3 AM, "
        "baseline aggregation every 6 hours, ML training on Sundays at 4 AM, "
        "scan watchdog every %d seconds",
        scan_mode,
        category_desc,
        signal_desc,
        settings.scan_watchdog_interval_seconds,
    )

    return scheduler
