"""
LeRobot Backend Logging Configuration

structlog 기반 구조화된 로깅 설정.
LOG_FORMAT 환경변수로 JSON/Console 출력 전환 가능.
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from .config import settings


def setup_logging() -> None:
    """애플리케이션 로깅을 초기화합니다.

    환경변수:
        LOG_LEVEL: 로깅 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        LOG_FORMAT: 출력 형식 (json, console)
    """
    # 로그 레벨 설정
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # 공통 프로세서
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    # 출력 형식에 따른 렌더러 선택
    if settings.LOG_FORMAT.lower() == "json":
        # JSON 형식 (프로덕션)
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        # Console 형식 (개발)
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
        )

    # structlog 설정
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # stdlib 로깅 포맷터
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # 핸들러 설정
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # uvicorn 로거 레벨 조정
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        logging.getLogger(logger_name).setLevel(log_level)

    # SQLAlchemy 로거 (DB_ECHO가 True일 때만 DEBUG)
    if settings.DB_ECHO:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.DEBUG)
    else:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """이름이 지정된 로거를 반환합니다.

    Args:
        name: 로거 이름 (보통 __name__ 사용)

    Returns:
        structlog BoundLogger 인스턴스

    Example:
        logger = get_logger(__name__)
        logger.info("사용자 로그인", user_id=123)
    """
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """현재 컨텍스트에 값을 바인딩합니다.

    이후 모든 로그에 해당 값이 포함됩니다.

    Args:
        **kwargs: 바인딩할 키-값 쌍

    Example:
        bind_context(request_id="abc-123", user_id=456)
        logger.info("요청 처리 중")  # request_id, user_id 포함
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """현재 컨텍스트를 초기화합니다."""
    structlog.contextvars.clear_contextvars()
