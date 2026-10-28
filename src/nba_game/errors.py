"""Shared application-specific exceptions."""


class NbaGameError(Exception):
    """Base error for expected application failures."""


class FetchError(NbaGameError):
    """Raised when an API request cannot be completed."""


class SourceBlockedError(Exception):
    """Raised when NBA serves HTML instead of API data (not proof of a block)."""

    def __init__(
        self, message: str, *, status_code: int | None = None, akamai: bool = False
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.akamai = akamai


class ResponseValidationError(NbaGameError):
    """Raised when an API response is not a complete game response."""


class StorageError(NbaGameError):
    """Raised when output cannot be saved safely."""
