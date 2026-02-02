"""FastAPI dependencies."""

from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.session import get_db


async def get_database() -> AsyncSession:
    """Dependency for database session."""
    async for session in get_db():
        yield session
        break  # Only yield once, as FastAPI handles the session lifecycle


async def require_admin_api_key(
    x_admin_api_key: str = Header(..., alias="X-Admin-API-Key")
) -> None:
    """
    Dependency to require admin API key for protected endpoints.
    
    Args:
        x_admin_api_key: Admin API key from X-Admin-API-Key header
        
    Raises:
        HTTPException: 401 if header missing, 403 if invalid
    """
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key not configured"
        )
    
    if x_admin_api_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin API key"
        )
