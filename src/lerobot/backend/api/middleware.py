"""
LeRobot Backend API Middleware

요청 ID 생성 및 에러 핸들링 미들웨어.
"""

import uuid
import time
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..core.logging import get_logger, bind_context, clear_context

logger = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """모든 요청에 고유 ID를 부여하는 미들웨어.

    요청 헤더에 X-Request-ID가 있으면 사용하고,
    없으면 새로운 UUID를 생성합니다.

    응답 헤더에도 X-Request-ID를 포함합니다.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 요청 ID 추출 또는 생성
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        # 컨텍스트에 바인딩 (이후 모든 로그에 포함)
        bind_context(request_id=request_id)

        # 요청 정보 저장
        request.state.request_id = request_id

        # 요청 처리
        response = await call_next(request)

        # 응답 헤더에 요청 ID 추가
        response.headers["X-Request-ID"] = request_id

        # 컨텍스트 정리
        clear_context()

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """HTTP 요청/응답 로깅 미들웨어.

    요청 시작과 완료 시 로그를 기록합니다.
    처리 시간도 함께 기록합니다.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()

        # 요청 로깅 (DEBUG 레벨)
        logger.debug(
            "요청 시작",
            method=request.method,
            path=request.url.path,
            query=str(request.query_params) if request.query_params else None,
        )

        # 요청 처리
        response = await call_next(request)

        # 처리 시간 계산
        process_time = (time.perf_counter() - start_time) * 1000  # ms

        # 응답 로깅
        log_level = "warning" if response.status_code >= 400 else "info"
        getattr(logger, log_level)(
            "요청 완료",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            process_time_ms=round(process_time, 2),
        )

        # 처리 시간 헤더 추가
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"

        return response


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """HTTP 예외 핸들러.

    FastAPI의 HTTPException을 처리합니다.
    """
    from fastapi import HTTPException

    if isinstance(exc, HTTPException):
        logger.warning(
            "HTTP 예외",
            status_code=exc.status_code,
            detail=exc.detail,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.status_code,
                    "message": exc.detail,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    # 예상치 못한 예외
    logger.error(
        "처리되지 않은 예외",
        error=str(exc),
        error_type=type(exc).__name__,
        path=request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": 500,
                "message": "Internal Server Error",
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Pydantic 유효성 검사 예외 핸들러."""
    from fastapi.exceptions import RequestValidationError

    if isinstance(exc, RequestValidationError):
        logger.warning(
            "유효성 검사 실패",
            errors=exc.errors(),
            path=request.url.path,
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": 422,
                    "message": "Validation Error",
                    "details": exc.errors(),
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    return await http_exception_handler(request, exc)
