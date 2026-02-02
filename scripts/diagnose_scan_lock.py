#!/usr/bin/env python3
"""
Diagnose scan lock state and provide recovery recommendations.
"""

import asyncio
from datetime import datetime
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from src.db.models import ScanJob
from src.db.session import AsyncSessionLocal
from src.worker.scan_lock import (
    ScanLockManager,
    LOCK_KEY,
    HEARTBEAT_KEY,
    PENDING_KEY,
)


async def diagnose() -> None:
    lock_manager = ScanLockManager()
    redis_client = await lock_manager._get_redis()

    lock_info = await lock_manager.get_lock_info()
    heartbeat_age = await lock_manager.get_heartbeat_age()
    pending = await redis_client.get(PENDING_KEY)

    print("Scan Lock Diagnosis")
    print("===================")
    print(f"LOCK_KEY: {LOCK_KEY}")
    print(f"HEARTBEAT_KEY: {HEARTBEAT_KEY}")
    print(f"PENDING_KEY: {PENDING_KEY}")
    print("")

    if not lock_info:
        print("Lock: none")
    else:
        run_id = lock_info.get("run_id")
        token = lock_info.get("token")
        ttl = lock_info.get("ttl_seconds")
        started_at = lock_info.get("started_at")
        print("Lock: present")
        print(f"  run_id: {run_id}")
        print(f"  token: {token}")
        print(f"  started_at: {started_at}")
        print(f"  ttl_seconds: {ttl}")

    print(f"Heartbeat age (seconds): {heartbeat_age}")
    print(f"Pending flag: {'set' if pending else 'not set'}")
    print("")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScanJob).where(ScanJob.status == "running").order_by(ScanJob.started_at.desc())
        )
        running_jobs = result.scalars().all()

        if not running_jobs:
            print("Running ScanJobs: none")
        else:
            print(f"Running ScanJobs: {len(running_jobs)}")
            for job in running_jobs:
                age_s = None
                if job.started_at:
                    age_s = (datetime.utcnow() - job.started_at).total_seconds()
                age_display = f"{age_s:.0f}" if age_s is not None else "n/a"
                print(
                    f"  - id={job.id} run_id={job.run_id} started_at={job.started_at} "
                    f"age_s={age_display} trigger={job.trigger} job_type={job.job_type}"
                )

    print("")
    print("Recommendations")
    print("----------------")
    if lock_info and not heartbeat_age:
        print("- Lock exists but heartbeat missing. Consider force-unlock.")
    if heartbeat_age and heartbeat_age > 300:
        print("- Heartbeat is stale (> 300s). Lock likely stuck; clear lock and mark job failed.")
    if lock_info and heartbeat_age is not None and heartbeat_age <= 300:
        print("- Heartbeat appears healthy. If scans still skip, check job status in DB.")
    if lock_info and not pending:
        print("- Manual scans during active scan will set pending flag.")
    if not lock_info and running_jobs:
        print("- Running ScanJob without lock present. Consider marking job failed.")
    if not lock_info and not running_jobs:
        print("- No issues detected.")


if __name__ == "__main__":
    asyncio.run(diagnose())
