"""Academic Profile public package API."""

from .generator import generate_profile
from .validation import validate_repository

__all__ = ["generate_profile", "validate_repository"]
__version__ = "0.1.0"

