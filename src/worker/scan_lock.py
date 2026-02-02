"""Redis-based distributed lock for scan coordination."""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import uuid4

import redis.asyncio as redis

from src.config import settings

logger = logging.getLogger(__name__)

# Redis keys for scan lock system
LOCK_KEY = "scan:category:lock"
HEARTBEAT_KEY = "scan:category:heartbeat"
PENDING_KEY = "scan:category:pending"


class ScanLockManager:
    """
    Manages distributed scan lock using Redis.
    
    Features:
    - TTL-based expiration (2 hours default)
    - Heartbeat key tracking last refresh
    - Token-based ownership verification
    - Pending queue for manual scans
    - Lock info retrieval
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize lock manager.
        
        Args:
            redis_url: Redis connection URL (defaults to settings)
        """
        self.redis_url = redis_url or settings.redis_url
        self._redis: Optional[redis.Redis] = None
    
    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis
    
    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
    
    async def acquire_lock(
        self,
        run_id: str,
        ttl_seconds: int = 7200,
    ) -> Optional[str]:
        """
        Acquire distributed lock for scan.
        
        Args:
            run_id: Unique run identifier (UUID hex)
            ttl_seconds: Time-to-live in seconds (default 2 hours)
            
        Returns:
            Token string if lock acquired, None if already held
        """
        redis_client = await self._get_redis()

        token = uuid4().hex
        lock_value = json.dumps({
            "run_id": run_id,
            "token": token,
            "started_at": datetime.utcnow().isoformat(),
        })
        
        # Use SET with NX (only if not exists) and EX (expiration)
        acquired = await redis_client.set(
            LOCK_KEY,
            lock_value,
            nx=True,  # Only set if key doesn't exist
            ex=ttl_seconds,  # Expiration in seconds
        )
        
        if acquired:
            await redis_client.set(
                HEARTBEAT_KEY,
                str(time.time()),
                ex=ttl_seconds,
            )
            logger.info(f"Acquired scan lock for run_id: {run_id[:16]}...")
            return token
        else:
            existing_value = await redis_client.get(LOCK_KEY)
            if existing_value:
                try:
                    existing_data = json.loads(existing_value)
                    existing_run_id = existing_data.get("run_id", "unknown")
                    logger.debug(
                        f"Lock already held by run_id: {existing_run_id[:16]}..."
                    )
                except (json.JSONDecodeError, KeyError):
                    logger.warning(f"Lock exists but value is invalid: {existing_value}")
        
        return None
    
    async def release_lock(self, run_id: str, token: Optional[str] = None) -> bool:
        """
        Release lock (safe unlock - only if value matches).
        
        Args:
            run_id: Run identifier to verify ownership
            token: Token to verify ownership
            
        Returns:
            True if lock released, False if not owned or already released
        """
        return await self.safe_unlock(run_id, token=token)
    
    async def safe_unlock(
        self,
        run_id: str,
        token: Optional[str] = None,
        force: bool = False,
    ) -> bool:
        """
        Safely unlock - only delete if value matches run_id (atomic operation).
        
        This prevents accidentally releasing a lock held by a different run.
        
        Args:
            run_id: Run identifier to verify ownership
            token: Token to verify ownership
            force: Force unlock without token (used by watchdog/admin recovery)
            
        Returns:
            True if lock released, False if not owned or already released
        """
        redis_client = await self._get_redis()
        if force:
            return await self.force_unlock()

        # Lua script to atomically verify run_id + token and delete lock + heartbeat
        # Returns: 0 = not found/already released, 1 = deleted, 2 = mismatch
        # On JSON decode error, do not delete without force
        lua_script = """
        local lock_value = redis.call('GET', KEYS[1])
        if not lock_value then
            return 0
        end
        
        local cjson = require('cjson')
        local success, data = pcall(cjson.decode, lock_value)
        if not success then
            return 2
        end
        
        if data.run_id == ARGV[1] and data.token == ARGV[2] then
            redis.call('DEL', KEYS[1])
            redis.call('DEL', KEYS[2])
            return 1
        else
            return 2
        end
        """
        
        if not token:
            logger.warning("Unlock requested without token; refusing (use force=True for recovery).")
            return False

        try:
            result = await redis_client.eval(
                lua_script,
                2,  # Number of keys
                LOCK_KEY,
                HEARTBEAT_KEY,
                run_id,
                token,
            )
            
            if result == 0:
                logger.debug("Lock already released")
                return True
            elif result == 1:
                logger.info(f"Released scan lock for run_id: {run_id[:16]}...")
                return True
            elif result == 2:
                logger.warning(
                    f"Attempted to release lock with mismatched token/run_id: "
                    f"requested={run_id[:16]}..."
                )
                return False
            else:
                logger.error(f"Unexpected Lua script result: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error executing safe_unlock Lua script: {e}")
            return False

    async def force_unlock(self) -> bool:
        """Force unlock without token verification (watchdog/admin use)."""
        redis_client = await self._get_redis()
        try:
            await redis_client.delete(LOCK_KEY, HEARTBEAT_KEY)
            logger.warning("Force-cleared scan lock and heartbeat keys")
            return True
        except Exception as e:
            logger.error(f"Failed to force unlock: {e}")
            return False

    async def request_run_after_current(self, ttl_seconds: Optional[int] = None) -> bool:
        """Set a pending flag so a scan runs immediately after the current one."""
        redis_client = await self._get_redis()
        ttl = ttl_seconds or settings.scan_lock_ttl_seconds
        try:
            pending_set = await redis_client.set(
                PENDING_KEY,
                "1",
                ex=ttl,
                nx=True,
            )
            if pending_set:
                logger.info("Queued a pending scan request")
            return bool(pending_set)
        except Exception as e:
            logger.error(f"Failed to set pending scan flag: {e}")
            return False

    async def consume_pending(self) -> bool:
        """Consume and clear the pending scan flag (atomic)."""
        redis_client = await self._get_redis()
        lua_script = """
        local pending = redis.call('GET', KEYS[1])
        if pending then
            redis.call('DEL', KEYS[1])
            return 1
        end
        return 0
        """
        try:
            result = await redis_client.eval(lua_script, 1, PENDING_KEY)
            return result == 1
        except Exception as e:
            logger.error(f"Failed to consume pending scan flag: {e}")
            return False
    
    async def refresh_lock(
        self,
        run_id: str,
        token: str,
        ttl_seconds: int = 7200,
    ) -> bool:
        """
        Refresh lock TTL (heartbeat) atomically using Lua script.
        
        Args:
            run_id: Run identifier to verify ownership
            token: Token to verify ownership
            ttl_seconds: New TTL in seconds
            
        Returns:
            True if lock refreshed, False if not owned or expired
        """
        redis_client = await self._get_redis()
        
        # Lua script to atomically verify run_id + token, refresh TTL, and update heartbeat
        # Returns: 0 = not found, 1 = refreshed, 2 = mismatch
        lua_script = """
        local lock_value = redis.call('GET', KEYS[1])
        if not lock_value then
            return 0
        end
        
        local cjson = require('cjson')
        local success, data = pcall(cjson.decode, lock_value)
        if not success then
            return 0
        end
        
        if data.run_id == ARGV[1] and data.token == ARGV[2] then
            redis.call('EXPIRE', KEYS[1], ARGV[3])
            redis.call('SET', KEYS[2], ARGV[4], 'EX', ARGV[3])
            return 1
        else
            return 2
        end
        """
        
        try:
            result = await redis_client.eval(
                lua_script,
                2,  # Number of keys
                LOCK_KEY,
                HEARTBEAT_KEY,
                run_id,
                token,
                str(ttl_seconds),
                str(time.time()),
            )
            
            if result == 0:
                logger.debug("Lock not found (may have expired)")
                return False
            elif result == 1:
                logger.debug(f"Refreshed lock TTL for run_id: {run_id[:16]}...")
                return True
            elif result == 2:
                logger.warning(
                    f"Attempted to refresh lock with mismatched token/run_id: "
                    f"requested={run_id[:16]}..."
                )
                return False
            else:
                logger.error(f"Unexpected Lua script result: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error executing refresh_lock Lua script: {e}")
            return False
    
    async def get_lock_info(self) -> Optional[Dict[str, Any]]:
        """
        Get current lock information.
        
        Returns:
            Dict with run_id, started_at, ttl, or None if no lock
        """
        redis_client = await self._get_redis()
        
        # Get lock value and TTL
        value = await redis_client.get(LOCK_KEY)
        ttl = await redis_client.ttl(LOCK_KEY)
        
        if not value:
            return None
        
        try:
            data = json.loads(value)
            return {
                "run_id": data.get("run_id"),
                "token": data.get("token"),
                "started_at": data.get("started_at"),
                "ttl_seconds": ttl if ttl > 0 else None,
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Invalid lock value format: {e}")
            return {
                "raw_value": value,
                "ttl_seconds": ttl if ttl > 0 else None,
            }

    async def get_heartbeat_age(self) -> Optional[float]:
        """Return seconds since last heartbeat, or None if missing."""
        redis_client = await self._get_redis()
        value = await redis_client.get(HEARTBEAT_KEY)
        if not value:
            return None
        try:
            last_ts = float(value)
        except (ValueError, TypeError):
            return None
        return max(0.0, time.time() - last_ts)


async def refresh_lock_heartbeat(
    redis_client: redis.Redis,
    run_id: str,
    token: str,
    interval: int = 45,
    ttl: int = 7200,
) -> None:
    """
    Background task to refresh lock TTL periodically (heartbeat).
    
    Args:
        redis_client: Redis client instance
        run_id: Run identifier
        interval: Refresh interval in seconds
        ttl: TTL to set on each refresh
    """
    lock_manager = ScanLockManager()
    lock_manager._redis = redis_client
    failure_count = 0
    
    try:
        while True:
            await asyncio.sleep(interval)
            
            refreshed = await lock_manager.refresh_lock(run_id, token, ttl)
            if not refreshed:
                failure_count += 1
                logger.warning(
                    f"Heartbeat failed for run_id: {run_id[:16]}... "
                    f"(consecutive failures: {failure_count})"
                )
                if failure_count >= 3:
                    logger.error(
                        f"Heartbeat stopping after {failure_count} failures for run_id: "
                        f"{run_id[:16]}..."
                    )
                    break
            else:
                failure_count = 0
    except asyncio.CancelledError:
        logger.debug(f"Heartbeat cancelled for run_id: {run_id[:16]}...")
        raise
    except Exception as e:
        logger.error(f"Heartbeat error: {e}", exc_info=True)


# Global lock manager instance
scan_lock_manager = ScanLockManager()
