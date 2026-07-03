from fastapi import HTTPException
from typing import Any, Dict, Optional

class AppError(HTTPException):
    """Base class for application-specific errors."""
    def __init__(self, status_code: int, code: str, message: str, details: Optional[Any] = None):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.details = details

class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(status_code=404, code="NOT_FOUND", message=message)

class ConflictError(AppError):
    def __init__(self, message: str = "Resource conflict exists"):
        super().__init__(status_code=409, code="CONFLICT", message=message)

class AuthError(AppError):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(status_code=401, code="UNAUTHORIZED", message=message)

class ValidationError(AppError):
    def __init__(self, message: str = "Invalid input", details: Optional[Any] = None):
        super().__init__(status_code=422, code="VALIDATION_ERROR", message=message, details=details)
