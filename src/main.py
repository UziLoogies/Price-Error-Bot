"""Main application entry point."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from prometheus_fastapi_instrumentator import Instrumentator

from src.config import settings
from src.db.session import engine
from src.db.models import Base
from src.worker.scheduler import setup_scheduler
from src.worker.tasks import task_runner
from src.api.routes import alerts, products, rules, stores, webhooks, dashboard, proxies, categories, scans, exclusions, notifications
from src import metrics
from src.ingest.proxy_manager import proxy_rotator
from src.db.session import AsyncSessionLocal

# Configure structured logging
from src.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Global scheduler
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global scheduler

    # Startup
    logger.info("Starting Price Error Bot...")

    # Initialize database
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize proxy rotator with database session factory
    proxy_rotator.set_session_factory(AsyncSessionLocal)
    await proxy_rotator.load_proxies()
    logger.info(f"Loaded {proxy_rotator.proxy_count} proxies")

    # Initialize task runner
    await task_runner.initialize()

    # Start scheduler
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("Scheduler started")

    yield

    # Shutdown
    logger.info("Shutting down...")

    if scheduler:
        scheduler.shutdown()

    await task_runner.close()
    
    # Close scanner HTTP clients
    from src.ingest.scan_engine import scan_engine
    if hasattr(scan_engine, 'scanner') and scan_engine.scanner is not None:
        try:
            await scan_engine.scanner.close()
        except Exception:
            logger.exception("Error closing scanner HTTP clients")

    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Price Error Bot",
    description="Monitor e-commerce prices and detect errors",
    version="0.1.0",
    lifespan=lifespan,
)

# Add Prometheus instrumentation
instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_respect_env_var=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/metrics", "/health", "/favicon.ico"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
)
instrumentator.instrument(app).expose(app, include_in_schema=True, tags=["monitoring"])

# Setup templates
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Include API routes
app.include_router(products.router)
app.include_router(rules.router)
app.include_router(webhooks.router)
app.include_router(alerts.router)
app.include_router(stores.router)
app.include_router(dashboard.router)
app.include_router(proxies.router)
app.include_router(categories.router)
app.include_router(scans.router)
app.include_router(exclusions.router)
app.include_router(notifications.router)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root endpoint - renders the dashboard UI."""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/favicon.ico")
async def favicon():
    """Return empty favicon response to avoid 404 noise."""
    return Response(status_code=204)


if __name__ == "__main__":
    # Run with uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
