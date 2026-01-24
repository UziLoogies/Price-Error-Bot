"""Proxy configuration API routes."""

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_database
from src.db.models import ProxyConfig
from src.ingest.proxy_manager import proxy_rotator, ProxyInfo

router = APIRouter(prefix="/api/proxies", tags=["proxies"])


class ProxyCreate(BaseModel):
    """Request model for creating a proxy."""
    name: str
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    enabled: bool = True


class ProxyUpdate(BaseModel):
    """Request model for updating a proxy."""
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    enabled: Optional[bool] = None


class ProxyResponse(BaseModel):
    """Response model for proxy configuration."""
    id: int
    name: str
    host: str
    port: int
    username: Optional[str]
    enabled: bool
    last_used: Optional[datetime]
    last_success: Optional[datetime]
    failure_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class ProxyTestResult(BaseModel):
    """Result of proxy connectivity test."""
    success: bool
    message: str
    response_time_ms: Optional[float] = None


@router.get("", response_model=List[ProxyResponse])
async def list_proxies(db: AsyncSession = Depends(get_database)):
    """List all configured proxies."""
    query = select(ProxyConfig).order_by(ProxyConfig.created_at.desc())
    result = await db.execute(query)
    proxies = result.scalars().all()
    return proxies


@router.post("", response_model=ProxyResponse, status_code=201)
async def create_proxy(
    proxy_data: ProxyCreate,
    db: AsyncSession = Depends(get_database)
):
    """Create a new proxy configuration."""
    proxy = ProxyConfig(
        name=proxy_data.name,
        host=proxy_data.host,
        port=proxy_data.port,
        username=proxy_data.username,
        password=proxy_data.password,
        enabled=proxy_data.enabled,
    )

    db.add(proxy)
    await db.commit()
    await db.refresh(proxy)

    # Refresh proxy rotator
    await proxy_rotator.refresh()

    return proxy


@router.get("/{proxy_id}", response_model=ProxyResponse)
async def get_proxy(proxy_id: int, db: AsyncSession = Depends(get_database)):
    """Get a specific proxy configuration."""
    query = select(ProxyConfig).where(ProxyConfig.id == proxy_id)
    result = await db.execute(query)
    proxy = result.scalar_one_or_none()

    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")

    return proxy


@router.put("/{proxy_id}", response_model=ProxyResponse)
async def update_proxy(
    proxy_id: int,
    proxy_data: ProxyUpdate,
    db: AsyncSession = Depends(get_database)
):
    """Update a proxy configuration."""
    query = select(ProxyConfig).where(ProxyConfig.id == proxy_id)
    result = await db.execute(query)
    proxy = result.scalar_one_or_none()

    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")

    # Update fields if provided
    if proxy_data.name is not None:
        proxy.name = proxy_data.name
    if proxy_data.host is not None:
        proxy.host = proxy_data.host
    if proxy_data.port is not None:
        proxy.port = proxy_data.port
    if proxy_data.username is not None:
        proxy.username = proxy_data.username
    if proxy_data.password is not None:
        proxy.password = proxy_data.password
    if proxy_data.enabled is not None:
        proxy.enabled = proxy_data.enabled
        # Reset failure count when re-enabling
        if proxy_data.enabled:
            proxy.failure_count = 0

    await db.commit()
    await db.refresh(proxy)

    # Refresh proxy rotator
    await proxy_rotator.refresh()

    return proxy


@router.delete("/{proxy_id}", status_code=204)
async def delete_proxy(proxy_id: int, db: AsyncSession = Depends(get_database)):
    """Delete a proxy configuration."""
    query = select(ProxyConfig).where(ProxyConfig.id == proxy_id)
    result = await db.execute(query)
    proxy = result.scalar_one_or_none()

    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")

    await db.delete(proxy)
    await db.commit()

    # Refresh proxy rotator
    await proxy_rotator.refresh()


@router.post("/{proxy_id}/test", response_model=ProxyTestResult)
async def test_proxy(proxy_id: int, db: AsyncSession = Depends(get_database)):
    """Test proxy connectivity."""
    import time

    query = select(ProxyConfig).where(ProxyConfig.id == proxy_id)
    result = await db.execute(query)
    proxy_model = result.scalar_one_or_none()

    if not proxy_model:
        raise HTTPException(status_code=404, detail="Proxy not found")

    proxy_info = ProxyInfo(
        id=proxy_model.id,
        host=proxy_model.host,
        port=proxy_model.port,
        username=proxy_model.username,
        password=proxy_model.password,
    )

    start_time = time.time()
    success = await proxy_rotator.test_proxy(proxy_info)
    response_time = (time.time() - start_time) * 1000  # Convert to ms

    if success:
        # Update last_success
        proxy_model.last_success = datetime.utcnow()
        proxy_model.failure_count = 0
        await db.commit()

        return ProxyTestResult(
            success=True,
            message=f"Proxy {proxy_model.host}:{proxy_model.port} is working",
            response_time_ms=response_time,
        )
    else:
        proxy_model.failure_count += 1
        await db.commit()

        return ProxyTestResult(
            success=False,
            message=f"Proxy {proxy_model.host}:{proxy_model.port} failed to connect",
        )


@router.post("/test-new", response_model=ProxyTestResult)
async def test_new_proxy(proxy_data: ProxyCreate):
    """Test a proxy before saving it."""
    import time

    proxy_info = ProxyInfo(
        id=0,
        host=proxy_data.host,
        port=proxy_data.port,
        username=proxy_data.username,
        password=proxy_data.password,
    )

    start_time = time.time()
    success = await proxy_rotator.test_proxy(proxy_info)
    response_time = (time.time() - start_time) * 1000

    if success:
        return ProxyTestResult(
            success=True,
            message=f"Proxy {proxy_data.host}:{proxy_data.port} is working",
            response_time_ms=response_time,
        )
    else:
        return ProxyTestResult(
            success=False,
            message=f"Proxy {proxy_data.host}:{proxy_data.port} failed to connect",
        )


@router.post("/refresh", status_code=200)
async def refresh_proxies():
    """Refresh the proxy rotation pool from database."""
    await proxy_rotator.refresh()
    return {"message": f"Refreshed {proxy_rotator.proxy_count} proxies"}
