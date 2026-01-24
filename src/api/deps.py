"""FastAPI dependencies."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db


async def get_database() -> AsyncSession:
    """Dependency for database session."""
    async for session in get_db():
        yield session
        break  # Only yield once, as FastAPI handles the session lifecycle
