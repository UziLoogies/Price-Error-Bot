"""Watchdog task to detect and recover from stale scan locks."""

import logging
from datetime import datetime

from sqlalchemy import select
from src.db.models import ScanJob
from src.db.session import AsyncSessionLocal
from src.worker.scan_lock import scan_lock_manager
from src.config import settings
from src import metrics

logger = logging.getLogger(__name__)


async def scan_watchdog_check(
    heartbeat_stale_seconds: int = 300,
    reason_prefix: str = "Watchdog",
) -> None:
    """
    Check for stale scan locks and recover.
    
    Logic:
    1. Check if Redis lock exists
    2. If exists, extract run_id from lock value
    3. Query DB for ScanJob with matching run_id and status="RUNNING"
    4. If no matching job OR job is older than MAX_SCAN_SECONDS:
       - Mark job as FAILED with error "Watchdog: stale lock detected"
       - Clear Redis lock
       - Log recovery action
    """
    try:
        # Get lock info + heartbeat age
        lock_info = await scan_lock_manager.get_lock_info()
        heartbeat_age = await scan_lock_manager.get_heartbeat_age()
        metrics.update_scan_lock_heartbeat_age(heartbeat_age)
        
        if not lock_info:
            # No lock exists - nothing to check
            return
        
        run_id = lock_info.get("run_id")
        if not run_id:
            logger.warning("%s: Lock exists but has no run_id - clearing invalid lock", reason_prefix)
            # Force clear invalid lock
            await scan_lock_manager.force_unlock()
            metrics.record_scan_lock_stale_recovered()
            return
        
        # Query DB for matching ScanJob
        async with AsyncSessionLocal() as db:
            query = select(ScanJob).where(
                ScanJob.run_id == run_id,
                ScanJob.status == "running"
            )
            result = await db.execute(query)
            scan_job = result.scalar_one_or_none()
            
            if not scan_job:
                # Lock exists but no RUNNING job found - stale lock
                logger.warning(
                    f"{reason_prefix}: Stale lock detected (run_id: {run_id[:16]}...). "
                    "No matching RUNNING job found. Clearing lock."
                )
                
                # Clear lock
                await scan_lock_manager.force_unlock()
                metrics.record_scan_lock_stale_recovered()
                return
            
            # Check heartbeat age (or missing heartbeat with old job)
            job_elapsed = None
            if scan_job.started_at:
                job_elapsed = (datetime.utcnow() - scan_job.started_at).total_seconds()

            if heartbeat_age is None and job_elapsed is not None and job_elapsed > heartbeat_stale_seconds:
                logger.warning(
                    f"{reason_prefix}: Missing heartbeat for run_id: {run_id[:16]}... "
                    f"(job age: {job_elapsed:.0f}s > {heartbeat_stale_seconds}s). "
                    "Marking job failed and clearing lock."
                )
                scan_job.status = "failed"
                scan_job.completed_at = datetime.utcnow()
                scan_job.error_message = (
                    f"{reason_prefix}: missing heartbeat detected. "
                    f"Job age {job_elapsed:.0f}s (> {heartbeat_stale_seconds}s)"
                )
                await db.commit()
                await scan_lock_manager.force_unlock()
                metrics.record_scan_lock_stale_recovered()
                return

            if heartbeat_age is not None and heartbeat_age > heartbeat_stale_seconds:
                logger.warning(
                    f"{reason_prefix}: Stale heartbeat detected for run_id: {run_id[:16]}... "
                    f"(age: {heartbeat_age:.0f}s > {heartbeat_stale_seconds}s). "
                    "Marking job failed and clearing lock."
                )
                scan_job.status = "failed"
                scan_job.completed_at = datetime.utcnow()
                scan_job.error_message = (
                    f"{reason_prefix}: stale heartbeat detected. "
                    f"Heartbeat age {heartbeat_age:.0f}s (> {heartbeat_stale_seconds}s)"
                )
                await db.commit()
                await scan_lock_manager.force_unlock()
                metrics.record_scan_lock_stale_recovered()
                return

            # Check if job is older than MAX_SCAN_SECONDS
            if scan_job.started_at:
                elapsed = (datetime.utcnow() - scan_job.started_at).total_seconds()
                
                if elapsed > settings.max_scan_duration_seconds:
                    # Job has been running too long - mark as failed
                    logger.warning(
                        f"{reason_prefix}: Scan job {scan_job.id} (run_id: {run_id[:16]}...) "
                        f"has been running for {elapsed:.0f} seconds (> {settings.max_scan_duration_seconds}). "
                        "Marking as failed and clearing lock."
                    )
                    
                    scan_job.status = "failed"
                    scan_job.completed_at = datetime.utcnow()
                    scan_job.error_message = (
                        f"{reason_prefix}: stale lock detected. "
                        f"Job ran for {elapsed:.0f} seconds (> {settings.max_scan_duration_seconds} limit)"
                    )
                    await db.commit()
                    
                    # Clear lock
                    await scan_lock_manager.force_unlock()
                    metrics.record_scan_lock_stale_recovered()
                    return
            
            # Job exists and is recent - verify TTL is still refreshing
            ttl = lock_info.get("ttl_seconds")
            if ttl is not None and ttl < 60:
                # TTL is very low - heartbeat may have stopped
                logger.warning(
                    f"{reason_prefix}: Lock TTL is low ({ttl}s) for run_id: {run_id[:16]}... "
                    "Heartbeat may have stopped."
                )
                # Don't clear yet - wait for TTL to expire naturally
                return
            
            # Everything looks healthy
            logger.debug(
                f"{reason_prefix}: Lock healthy for run_id: {run_id[:16]}... "
                f"(job_id: {scan_job.id}, TTL: {ttl}s, heartbeat_age: {heartbeat_age})"
            )
    
    except Exception as e:
        logger.error(f"Watchdog check failed: {e}", exc_info=True)
