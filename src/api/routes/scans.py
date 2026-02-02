"""Scan management API endpoints."""

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_database, require_admin_api_key
from src.db.models import ScanJob, StoreCategory
from src.ingest.scan_engine import scan_engine, ScanProgress
from src.worker.tasks import task_runner
from src.worker.scan_lock import scan_lock_manager

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scans", tags=["scans"])


# Response models
class ScanJobResponse(BaseModel):
    """Response model for scan job."""
    id: int
    job_type: str
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    total_items: int
    processed_items: int
    success_count: int
    error_count: int
    products_found: int
    deals_found: int
    error_message: Optional[str]
    created_at: datetime
    progress_percent: float

    class Config:
        from_attributes = True


class ScanProgressResponse(BaseModel):
    """Response model for live scan progress."""
    job_id: int
    total_categories: int
    completed_categories: int
    total_products: int
    total_deals: int
    progress_percent: float
    errors: List[str]
    is_complete: bool


class TriggerScanRequest(BaseModel):
    """Request model for triggering a scan."""
    category_ids: Optional[List[int]] = None
    store: Optional[str] = None


class ScanStatsResponse(BaseModel):
    """Response model for scan statistics."""
    total_jobs: int
    jobs_today: int
    total_products_found: int
    total_deals_found: int
    average_success_rate: float
    last_scan_time: Optional[datetime]


@router.get("/jobs", response_model=List[ScanJobResponse])
async def list_scan_jobs(
    status: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_database)
):
    """List scan jobs, optionally filtered by status."""
    query = select(ScanJob).order_by(ScanJob.created_at.desc()).limit(limit)
    
    if status:
        query = query.where(ScanJob.status == status)
    
    result = await db.execute(query)
    jobs = result.scalars().all()
    
    # Add progress_percent to response
    response = []
    for job in jobs:
        job_dict = {
            "id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "total_items": job.total_items,
            "processed_items": job.processed_items,
            "success_count": job.success_count,
            "error_count": job.error_count,
            "products_found": job.products_found,
            "deals_found": job.deals_found,
            "error_message": job.error_message,
            "created_at": job.created_at,
            "progress_percent": job.progress_percent,
        }
        response.append(ScanJobResponse(**job_dict))
    
    return response


@router.get("/jobs/{job_id}", response_model=ScanJobResponse)
async def get_scan_job(job_id: int, db: AsyncSession = Depends(get_database)):
    """Get a specific scan job."""
    job = await db.get(ScanJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")
    
    return ScanJobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        started_at=job.started_at,
        completed_at=job.completed_at,
        total_items=job.total_items,
        processed_items=job.processed_items,
        success_count=job.success_count,
        error_count=job.error_count,
        products_found=job.products_found,
        deals_found=job.deals_found,
        error_message=job.error_message,
        created_at=job.created_at,
        progress_percent=job.progress_percent,
    )


@router.get("/jobs/{job_id}/progress", response_model=ScanProgressResponse)
async def get_scan_progress(job_id: int):
    """Get live progress for an active scan job."""
    progress = scan_engine.get_active_job(job_id)
    
    if not progress:
        raise HTTPException(
            status_code=404,
            detail="No active scan found with this ID. Job may have completed."
        )
    
    return ScanProgressResponse(
        job_id=progress.job_id,
        total_categories=progress.total_categories,
        completed_categories=progress.completed_categories,
        total_products=progress.total_products,
        total_deals=progress.total_deals,
        progress_percent=progress.progress_percent,
        errors=progress.errors,
        is_complete=progress.is_complete,
    )


@router.get("/active")
async def get_active_scans():
    """Get all currently active scans."""
    active_jobs = scan_engine.get_all_active_jobs()
    
    return [
        ScanProgressResponse(
            job_id=p.job_id,
            total_categories=p.total_categories,
            completed_categories=p.completed_categories,
            total_products=p.total_products,
            total_deals=p.total_deals,
            progress_percent=p.progress_percent,
            errors=p.errors,
            is_complete=p.is_complete,
        )
        for p in active_jobs.values()
    ]


@router.post("/trigger")
async def trigger_scan(
    request: TriggerScanRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger a manual scan.
    
    Uses the centralized scan_entrypoint with trigger="manual".
    If a scan is already running, the request is queued to run after completion.
    """
    job_id = f"manual_scan_{uuid4().hex}"
    lock_info = await scan_lock_manager.get_lock_info()
    if lock_info:
        await scan_lock_manager.request_run_after_current()
        return {
            "message": "Scan queued (lock held)",
            "queued": True,
            "job_id": job_id,
            "category_ids": request.category_ids,
            "store": request.store,
        }

    # Run scan asynchronously (lock handled in scan_entrypoint)
    background_tasks.add_task(task_runner.scan_entrypoint, trigger="manual")

    return {
        "message": "Scan triggered successfully",
        "queued": False,
        "job_id": job_id,
        "category_ids": request.category_ids,
        "store": request.store,
    }


@router.post("/trigger/category/{category_id}")
async def trigger_category_scan(
    category_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_database),
):
    """Trigger a scan for a specific category."""
    # Verify category exists
    category = await db.get(StoreCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    job_id = f"manual_scan_category_{category_id}_{uuid4().hex}"
    lock_info = await scan_lock_manager.get_lock_info()
    if lock_info:
        await scan_lock_manager.request_run_after_current()
        return {
            "message": f"Scan queued for category: {category.category_name}",
            "queued": True,
            "job_id": job_id,
            "category_id": category_id,
            "store": category.store,
        }

    background_tasks.add_task(task_runner.scan_entrypoint, trigger="manual")

    return {
        "message": f"Scan triggered for category: {category.category_name}",
        "queued": False,
        "job_id": job_id,
        "category_id": category_id,
        "store": category.store,
    }


@router.post("/admin/force-unlock")
async def force_unlock_scan(
    db: AsyncSession = Depends(get_database),
    _admin: None = Depends(require_admin_api_key),
):
    """
    Force unlock a stuck scan (admin only).
    
    This endpoint:
    1. Deletes the Redis lock if present
    2. Marks any RUNNING ScanJob as FAILED
    3. Returns current scan state
    
    Note: In production, this should be protected with authentication/authorization.
    """
    from src.worker.scan_lock import scan_lock_manager
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Get current lock info
    lock_info = await scan_lock_manager.get_lock_info()
    
    if not lock_info:
        return {
            "message": "No lock found",
            "lock_info": None,
            "jobs_updated": 0,
        }
    
    run_id = lock_info.get("run_id")
    
    # Find and update RUNNING jobs
    jobs_updated = 0
    if run_id:
        query = select(ScanJob).where(
            ScanJob.run_id == run_id,
            ScanJob.status == "running"
        )
        result = await db.execute(query)
        jobs = result.scalars().all()
        
        for job in jobs:
            job.status = "failed"
            job.completed_at = datetime.utcnow()
            job.error_message = "Forced unlock by admin"
            jobs_updated += 1
        
        await db.commit()
    
    # Delete lock
    await scan_lock_manager.force_unlock()
    
    logger.warning(
        f"Admin force-unlock executed (run_id: {run_id[:16] if run_id else 'unknown'}..., "
        f"jobs_updated: {jobs_updated})"
    )
    
    return {
        "message": "Lock force-unlocked",
        "lock_info": lock_info,
        "jobs_updated": jobs_updated,
    }


@router.get("/stats", response_model=ScanStatsResponse)
async def get_scan_stats(db: AsyncSession = Depends(get_database)):
    """Get scan statistics."""
    # Total jobs
    total_result = await db.execute(select(func.count(ScanJob.id)))
    total_jobs = total_result.scalar() or 0
    
    # Jobs today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_result = await db.execute(
        select(func.count(ScanJob.id)).where(ScanJob.created_at >= today_start)
    )
    jobs_today = today_result.scalar() or 0
    
    # Total products and deals
    products_result = await db.execute(
        select(func.sum(ScanJob.products_found))
    )
    total_products = products_result.scalar() or 0
    
    deals_result = await db.execute(
        select(func.sum(ScanJob.deals_found))
    )
    total_deals = deals_result.scalar() or 0
    
    # Average success rate
    completed_jobs = await db.execute(
        select(ScanJob).where(ScanJob.status == "completed")
    )
    jobs = completed_jobs.scalars().all()
    
    if jobs:
        success_rates = []
        for job in jobs:
            total = job.success_count + job.error_count
            if total > 0:
                success_rates.append(job.success_count / total)
        avg_success_rate = sum(success_rates) / len(success_rates) if success_rates else 0
    else:
        avg_success_rate = 0
    
    # Last scan time
    last_job_result = await db.execute(
        select(ScanJob.completed_at)
        .where(ScanJob.status == "completed")
        .order_by(ScanJob.completed_at.desc())
        .limit(1)
    )
    last_scan_time = last_job_result.scalar()
    
    return ScanStatsResponse(
        total_jobs=total_jobs,
        jobs_today=jobs_today,
        total_products_found=total_products,
        total_deals_found=total_deals,
        average_success_rate=avg_success_rate,
        last_scan_time=last_scan_time,
    )
