"""Shared utility for loading ML models with security validation and fallback support."""

import logging
import pickle
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_model_with_fallback(model_path: Path) -> Any:
    """
    Load a model from disk with security validation and fallback support.
    
    Validates the path, attempts joblib.load first (safer), then falls back
    to pickle.load if joblib is unavailable. Returns the loaded model or
    raises a clear exception.
    
    Args:
        model_path: Path to the model file
        
    Returns:
        The loaded model object
        
    Raises:
        FileNotFoundError: If the model file doesn't exist
        ValueError: If the model path is outside the allowed directory
        RuntimeError: If model loading fails for any other reason
        
    Security:
        Model files must be from trusted sources only. The path is validated
        to ensure it's within the allowed directory (data/models).
    """
    # Validate path exists
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model file not found: {model_path}"
        )
    
    # Validate model path is within allowed directory
    # Model files must be from trusted sources only
    try:
        model_path_resolved = model_path.resolve()
        allowed_dir = Path("data/models").resolve()
        
        # Check if path is within allowed directory
        # Support both Python 3.9+ (is_relative_to) and older versions (relative_to)
        try:
            # Python 3.9+: use is_relative_to
            if not model_path_resolved.is_relative_to(allowed_dir):
                raise ValueError(
                    f"Model path {model_path} (resolved: {model_path_resolved}) "
                    f"is outside allowed directory {allowed_dir}"
                )
        except AttributeError:
            # Python <3.9: use relative_to with try/except
            try:
                model_path_resolved.relative_to(allowed_dir)
            except ValueError:
                raise ValueError(
                    f"Model path {model_path} (resolved: {model_path_resolved}) "
                    f"is outside allowed directory {allowed_dir}"
                )
    except ValueError:
        # Re-raise ValueError (path validation failed)
        raise
    except Exception as e:
        raise RuntimeError(
            f"Failed to validate model path {model_path}: {e}"
        ) from e
    
    # Attempt to load model
    try:
        # Try joblib first (safer than pickle)
        try:
            import joblib
            model = joblib.load(model_path)
            logger.info(f"Model loaded from {model_path} using joblib")
            return model
        except ImportError:
            # Fallback to pickle if joblib not available
            logger.warning("joblib not available, using pickle (less secure)")
            with open(model_path, "rb") as f:
                model = pickle.load(f)
            logger.info(f"Model loaded from {model_path} using pickle")
            return model
    except Exception as e:
        raise RuntimeError(
            f"Failed to load model from {model_path}: {e}"
        ) from e
