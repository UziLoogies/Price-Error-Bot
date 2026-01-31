"""Encryption utilities for sensitive database fields.

Provides transparent encryption/decryption for sensitive columns
using Fernet symmetric encryption.
"""

import base64
import logging
import os
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import TypeDecorator, String
from sqlalchemy.types import TypeEngine

from src import metrics

logger = logging.getLogger(__name__)


def get_encryption_key() -> bytes:
    """
    Get encryption key from environment variable.
    
    Returns:
        Encryption key as bytes
        
    Raises:
        ValueError: If encryption key is not set
    """
    key_str = os.getenv("ENCRYPTION_KEY")
    if not key_str:
        # Generate a key if not set (for development only)
        # In production, this should be set via environment variable
        logger.warning("ENCRYPTION_KEY not set, generating temporary key (not secure for production)")
        key = Fernet.generate_key()
        logger.warning(f"Generated key: {key.decode()}")
        return key
    
    # Key should be base64-encoded Fernet key (32 bytes, base64-encoded to 44 chars)
    try:
        # Try to decode as base64 first
        key_bytes = base64.urlsafe_b64decode(key_str)
        if len(key_bytes) == 32:
            return base64.urlsafe_b64encode(key_bytes)
        # If wrong length, generate from string
        return base64.urlsafe_b64encode(key_str.encode().ljust(32)[:32])
    except Exception:
        # If decoding fails, generate from string
        return base64.urlsafe_b64encode(key_str.encode().ljust(32)[:32])


class EncryptedString(TypeDecorator):
    """
    SQLAlchemy TypeDecorator for transparently encrypting/decrypting string columns.
    
    Usage:
        password: Mapped[Optional[str]] = mapped_column(EncryptedString(256), nullable=True)
    """
    
    impl = String
    cache_ok = True
    
    def __init__(self, length: int = 256, *args: Any, **kwargs: Any):
        super().__init__(length, *args, **kwargs)
        self._fernet: Fernet | None = None
    
    def _get_fernet(self) -> Fernet:
        """Get or create Fernet instance."""
        if self._fernet is None:
            key = get_encryption_key()
            self._fernet = Fernet(key)
        return self._fernet
    
    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        """Encrypt value before storing in database."""
        if value is None:
            return None
        
        try:
            fernet = self._get_fernet()
            encrypted = fernet.encrypt(value.encode())
            # Store as base64 string
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise
    
    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        """Decrypt value after reading from database."""
        if value is None:
            return None
        
        try:
            fernet = self._get_fernet()
            # Decode from base64
            encrypted = base64.urlsafe_b64decode(value.encode())
            decrypted = fernet.decrypt(encrypted)
            return decrypted.decode()
        except Exception as e:
            # Record metric for monitoring
            exception_type = type(e).__name__
            metrics.record_decryption_failure(exception_type)
            
            # Log with higher visibility and context
            logger.exception(
                f"Decryption failed: {exception_type}: {e} "
                f"(value_length={len(value)}). "
                f"This may indicate key rotation, data corruption, or legacy unencrypted data."
            )
            
            # Report to error tracking if available (Sentry/telemetry)
            # This allows external monitoring systems to track decryption failures
            try:
                # Check if Sentry is available
                import sentry_sdk
                sentry_sdk.capture_exception(e, contexts={
                    "decryption": {
                        "exception_type": exception_type,
                        "value_length": len(value),
                        "value_preview": value_preview,
                    }
                })
            except ImportError:
                # Sentry not installed, skip error reporting
                pass
            except Exception:
                # Don't fail if error reporting itself fails
                pass
            
            # Return None on decryption failure (could be old unencrypted data)
            # This preserves backward compatibility for migration scenarios
            return None


def encrypt_value(value: str) -> str:
    """
    Encrypt a value for storage.
    
    Args:
        value: Plaintext value to encrypt
        
    Returns:
        Encrypted value as base64 string
    """
    if not value:
        return value
    
    try:
        fernet = Fernet(get_encryption_key())
        encrypted = fernet.encrypt(value.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise


def decrypt_value(value: str) -> str | None:
    """
    Decrypt a value from storage.
    
    Args:
        value: Encrypted value as base64 string
        
    Returns:
        Decrypted plaintext value or None on failure
    """
    if not value:
        return value
    
    try:
        fernet = Fernet(get_encryption_key())
        encrypted = base64.urlsafe_b64decode(value.encode())
        decrypted = fernet.decrypt(encrypted)
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return None
