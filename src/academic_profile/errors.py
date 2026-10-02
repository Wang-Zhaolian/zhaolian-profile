class AcademicProfileError(Exception):
    """Base exception for user-facing project errors."""


class DataValidationError(AcademicProfileError):
    """Raised when generation is attempted with invalid data."""


class GenerationError(AcademicProfileError):
    """Raised when a requested output cannot be generated."""

