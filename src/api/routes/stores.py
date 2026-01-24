"""Store management routes."""

from fastapi import APIRouter

from src.ingest.registry import FetcherRegistry

router = APIRouter(prefix="/api/stores", tags=["stores"])


@router.get("")
async def list_stores():
    """List all available retailers."""
    stores = FetcherRegistry.list_stores()
    return {"stores": stores}
