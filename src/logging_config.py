"""Structured logging configuration for Loki integration."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from pythonjsonlogger import jsonlogger

from src.config import settings


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional fields for Loki."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        
        # Add timestamp in ISO format
        log_record['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        
        # Add log level
        log_record['level'] = record.levelname
        
        # Add logger name
        log_record['logger'] = record.name
        
        # Add source location
        log_record['source'] = f"{record.filename}:{record.lineno}"
        
        # Add function name
        if record.funcName:
            log_record['function'] = record.funcName


def setup_logging(base_dir: str | Path | None = None):
    """Configure logging for the application.
    
    Args:
        base_dir: Optional base directory to place the logs/ folder in.
                  If omitted, uses the current working directory.
    """

    # Create logs directory if it doesn't exist
    logs_dir = (Path(base_dir) if base_dir else Path.cwd()) / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler (human-readable for development)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (JSON for Loki/Promtail)
    json_handler = logging.FileHandler(logs_dir / "app.log")
    json_handler.setLevel(logging.DEBUG)
    json_formatter = CustomJsonFormatter(
        "%(timestamp)s %(level)s %(name)s %(message)s"
    )
    json_handler.setFormatter(json_formatter)
    root_logger.addHandler(json_handler)
    
    # Also add a separate file for errors only
    error_handler = logging.FileHandler(logs_dir / "error.log")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(json_formatter)
    root_logger.addHandler(error_handler)
    
    return root_logger


class LoggerAdapter(logging.LoggerAdapter):
    """Custom logger adapter that adds context fields to log records."""
    
    def process(self, msg, kwargs):
        # Add extra context to the message
        extra = kwargs.get('extra', {})
        extra.update(self.extra)
        kwargs['extra'] = extra
        return msg, kwargs


def get_logger(name: str, **context) -> LoggerAdapter:
    """
    Get a logger with optional context fields.
    
    Args:
        name: Logger name (usually __name__)
        **context: Additional context fields (e.g., store='amazon', sku='B001')
    
    Returns:
        LoggerAdapter with context
    """
    logger = logging.getLogger(name)
    return LoggerAdapter(logger, context)
