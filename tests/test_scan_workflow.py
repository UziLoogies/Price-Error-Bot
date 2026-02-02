"""Integration-style tests for scan workflow behavior."""

import pytest
import redis.asyncio as redis

from src.config import settings
from src.worker.scan_lock import ScanLockManager
from src.worker.tasks import task_runner


async def _redis_available() -> bool:
    try:
        client = await redis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        await client.close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_manual_scan_queues_when_lock_held():
    if not await _redis_available():
        pytest.skip("Redis not available")

    manager = ScanLockManager(redis_url=settings.redis_url)
    await manager.force_unlock()

    run_id = "lock_holder"
    token = await manager.acquire_lock(run_id, ttl_seconds=30)
    assert token is not None

    await task_runner.scan_entrypoint(trigger="manual")

    pending = await manager.consume_pending()
    assert pending is True

    await manager.safe_unlock(run_id, token=token)
