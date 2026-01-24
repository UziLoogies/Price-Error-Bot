# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Price Error Bot Desktop Launcher.

Build with: pyinstaller launcher.spec
Output: dist/PriceErrorBot.exe
"""

import sys
from pathlib import Path

block_cipher = None

# Get the project root
project_root = Path(SPECPATH)

# Collect all source modules
src_path = project_root / 'src'

# Data files to include (templates, static files, etc.)
datas = [
    # Include templates
    (str(src_path / 'templates'), 'src/templates'),
    # Include admin templates if they exist
    (str(src_path / 'admin' / 'templates'), 'src/admin/templates'),
    # Include docker-compose for container management
    (str(project_root / 'docker-compose.yml'), '.'),
    # Include alembic for migrations
    (str(project_root / 'alembic'), 'alembic'),
    (str(project_root / 'alembic.ini'), '.'),
    # Include category seed file
    (str(project_root / 'categories_seed.json'), '.'),
]

# Filter out non-existent paths
datas = [(src, dst) for src, dst in datas if Path(src).exists()]

a = Analysis(
    ['launcher.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # FastAPI and dependencies
        'fastapi',
        'uvicorn',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
        'starlette',
        'starlette.routing',
        'starlette.middleware',
        
        # Database
        'sqlalchemy',
        'sqlalchemy.ext.asyncio',
        'asyncpg',
        'psycopg2',
        
        # Redis
        'redis',
        'redis.asyncio',
        
        # Pydantic
        'pydantic',
        'pydantic_settings',
        
        # Scheduler
        'apscheduler',
        'apscheduler.schedulers.asyncio',
        'apscheduler.triggers.interval',
        'apscheduler.triggers.cron',
        
        # HTTP clients
        'httpx',
        
        # Templating
        'jinja2',
        
        # Web scraping
        'playwright',
        'beautifulsoup4',
        'bs4',
        'selectolax',
        
        # Monitoring
        'prometheus_client',
        'prometheus_fastapi_instrumentator',
        
        # Logging
        'pythonjsonlogger',
        
        # System utilities
        'psutil',
        
        # pywebview
        'webview',
        'webview.platforms.winforms',
        'clr_loader',
        'pythonnet',
        
        # Application modules
        'src',
        'src.main',
        'src.config',
        'src.db',
        'src.db.models',
        'src.db.session',
        'src.api',
        'src.api.routes',
        'src.api.routes.alerts',
        'src.api.routes.products',
        'src.api.routes.rules',
        'src.api.routes.stores',
        'src.api.routes.webhooks',
        'src.api.routes.dashboard',
        'src.api.routes.proxies',
        'src.api.routes.categories',
        'src.api.routes.scans',
        'src.api.routes.exclusions',
        'src.worker',
        'src.worker.scheduler',
        'src.worker.tasks',
        'src.ingest',
        'src.ingest.category_scanner',
        'src.ingest.proxy_manager',
        'src.ingest.scan_engine',
        'src.ingest.filters',
        'src.ingest.retailers',
        'src.detect',
        'src.detect.deal_detector',
        'src.detect.engine',
        'src.detect.rules',
        'src.notify',
        'src.notify.discord',
        'src.notify.dedupe',
        'src.normalize',
        'src.normalize.processor',
        'src.metrics',
        'src.logging_config',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude test modules
        'pytest',
        'pytest_asyncio',
        # Exclude dev tools
        'black',
        'ruff',
        # Exclude unused modules to reduce size
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PriceErrorBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Show console window so users can see live logs alongside the UI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add path to .ico file here if available, e.g., 'icon.ico'
    version=None,  # Add version info file here if available
)
