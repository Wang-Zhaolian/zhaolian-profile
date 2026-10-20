class AcademicProfileError(Exception):
    """Base exception for user-facing project errors."""


class DataValidationError(AcademicProfileError):
    """Raised when stored academic records fail schema validation."""


class GenerationError(AcademicProfileError):
    """Raised when a requested output cannot be generated."""
