from fastapi import HTTPException


# Machine-readable error codes
AUTH_REQUIRED = "AUTH_REQUIRED"
AUTH_INVALID = "AUTH_INVALID"
TASK_NOT_FOUND = "TASK_NOT_FOUND"
TASK_NOT_RETRYABLE = "TASK_NOT_RETRYABLE"
TRANSCRIPT_NOT_READY = "TRANSCRIPT_NOT_READY"
INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS"
VALIDATION_ERROR = "VALIDATION_ERROR"
SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(HTTPException):
    """Structured API error with machine-readable code."""

    def __init__(self, status_code: int, code: str, message: str, details: dict = None):
        self.code = code
        self.details = details
        super().__init__(status_code=status_code, detail=message)
