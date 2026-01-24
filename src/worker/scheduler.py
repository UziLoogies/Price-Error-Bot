"""APScheduler job definitions."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.worker.tasks import task_runner

logger = logging.getLogger(__name__)


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
        max_instances=1,
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

    logger.info(
        "Scheduler configured: category scan every 5 minutes, "
        "baseline recalculation at 3 AM"
    )

    return scheduler
