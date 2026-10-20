"""统一业务错误。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException


class ApiError(HTTPException):
    """带业务错误码的 HTTP 异常，响应结构由全局异常处理器统一包装。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Optional[Any] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message
        self.details = details


def bad_request(message: str, code: str = "BAD_REQUEST", details: Any = None) -> ApiError:
    return ApiError(400, code, message, details=details)


def unauthorized(message: str = "登录状态已失效，请重新登录", code: str = "UNAUTHORIZED") -> ApiError:
    return ApiError(401, code, message, headers={"WWW-Authenticate": "Bearer"})


def forbidden(message: str = "无权执行该操作", code: str = "FORBIDDEN") -> ApiError:
    return ApiError(403, code, message)


def not_found(message: str = "资源不存在", code: str = "NOT_FOUND") -> ApiError:
    return ApiError(404, code, message)


def conflict(message: str, code: str = "CONFLICT", details: Any = None) -> ApiError:
    return ApiError(409, code, message, details=details)


def validation_error(message: str = "参数校验失败", details: Any = None) -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", message, details=details)


def too_many_requests(message: str = "请求过于频繁，请稍后再试") -> ApiError:
    return ApiError(429, "RATE_LIMITED", message)
