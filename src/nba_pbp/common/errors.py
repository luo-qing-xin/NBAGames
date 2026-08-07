"""Shared application-specific exceptions."""


class NbaPbpError(Exception):
    """Base error for expected application failures."""


class FetchError(NbaPbpError):
    """Raised when an API request cannot be completed."""


class SourceBlockedError(Exception):
    """Raised when NBA serves an HTML block page instead of API data."""


class ResponseValidationError(NbaPbpError):
    """Raised when an API response is not a complete game response."""


class StorageError(NbaPbpError):
    """Raised when output cannot be saved safely."""
