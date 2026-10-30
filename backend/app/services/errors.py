"""Safe domain errors suitable for translation at the API boundary."""


class SentinelServiceError(Exception):
    """Base error for expected service failures."""


class ResourceNotFoundError(SentinelServiceError):
    """Raised when a requested persisted resource does not exist."""


class InvalidTargetConfigurationError(SentinelServiceError):
    """Raised when target settings cannot support a request or evaluation."""


class EvaluationExecutionError(SentinelServiceError):
    """Raised after an evaluation is safely marked failed."""


class ConflictError(SentinelServiceError):
    """An immutable identity already exists with different contents."""
