"""Sanitized application errors rendered by centralized FastAPI handlers."""

from __future__ import annotations


class ApiProblem(RuntimeError):
    """An intentionally public HTTP status/code/message triple."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.public_message = message
        self.headers = headers or {}
