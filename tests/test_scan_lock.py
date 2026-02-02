"""Tests for scan lock behavior."""

import pytest
import redis.asyncio as redis

from src.config import settings
from src.worker.scan_lock import ScanLockManager


async def _redis_available() -> bool:
    try:
        client = await redis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        await client.close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_lock_acquire_refresh_release():
    if not await _redis_available():
        pytest.skip("Redis not available")

    manager = ScanLockManager(redis_url=settings.redis_url)
    await manager.force_unlock()

    run_id = "test_run_lock"
    token = await manager.acquire_lock(run_id, ttl_seconds=30)
    assert token is not None

    info = await manager.get_lock_info()
    assert info is not None
    assert info.get("run_id") == run_id
    assert info.get("token") == token

    refreshed = await manager.refresh_lock(run_id, token, ttl_seconds=30)
    assert refreshed is True

    released = await manager.safe_unlock(run_id, token=token)
    assert released is True

    info = await manager.get_lock_info()
    assert info is None


@pytest.mark.asyncio
async def test_lock_token_mismatch():
    if not await _redis_available():
        pytest.skip("Redis not available")

    manager = ScanLockManager(redis_url=settings.redis_url)
    await manager.force_unlock()

    run_id = "test_run_token"
    token = await manager.acquire_lock(run_id, ttl_seconds=30)
    assert token is not None

    released = await manager.safe_unlock(run_id, token="bad_token")
    assert released is False

    await manager.force_unlock()


@pytest.mark.asyncio
async def test_pending_queue():
    if not await _redis_available():
        pytest.skip("Redis not available")

    manager = ScanLockManager(redis_url=settings.redis_url)
    await manager.force_unlock()

    pending_set = await manager.request_run_after_current(ttl_seconds=30)
    assert pending_set is True

    pending = await manager.consume_pending()
    assert pending is True

    pending_again = await manager.consume_pending()
    assert pending_again is False
