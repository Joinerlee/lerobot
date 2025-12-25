"""
LeRobot Backend Application Entry Point

FastAPI 애플리케이션 인스턴스 및 라우터 등록.

Usage:
    uvicorn src.lerobot.backend.main:app --reload

    또는

    cd src/lerobot/backend
    uvicorn main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from .core.config import settings
from .core.logging import setup_logging, get_logger
from .database import engine
from .models import Base
from .api.dependencies import verify_api_key
from .api.middleware import (
    RequestIdMiddleware,
    RequestLoggingMiddleware,
    http_exception_handler,
    validation_exception_handler,
)

# 로깅 초기화
setup_logging()
logger = get_logger(__name__)

from .api.routes import (
    health_router,
    robots_router,
    sessions_router,
    upload_router,
    websocket_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리.

    시작 시:
        - DB 테이블 생성
        - 백업 디렉토리 생성

    종료 시:
        - 리소스 정리
    """
    # Startup
    logger.info("애플리케이션 시작", app_name=settings.APP_NAME, version=settings.APP_VERSION)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("데이터베이스 테이블 초기화 완료")

    # 백업 디렉토리 생성
    settings.backup_path.mkdir(parents=True, exist_ok=True)
    logger.info("백업 디렉토리 준비 완료", path=str(settings.backup_path))

    yield

    # Shutdown
    logger.info("애플리케이션 종료")


app = FastAPI(
    title=settings.APP_NAME,
    description="Teleoperation data collection and dataset management API",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# =============================================================================
# Middleware Registration (순서 중요: 먼저 등록된 것이 바깥쪽)
# =============================================================================

app.add_middleware(RequestLoggingMiddleware)  # 요청/응답 로깅
app.add_middleware(RequestIdMiddleware)       # 요청 ID 생성

# =============================================================================
# Exception Handlers
# =============================================================================

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, http_exception_handler)

# =============================================================================
# Router Registration
# =============================================================================

# 인증 불필요 (헬스체크)
app.include_router(health_router)

# 인증 필요 (API_KEY 환경변수 설정 시)
auth_dependency = [Depends(verify_api_key)]
app.include_router(robots_router, dependencies=auth_dependency)
app.include_router(sessions_router, dependencies=auth_dependency)
app.include_router(upload_router, dependencies=auth_dependency)
app.include_router(websocket_router)  # WebSocket은 별도 처리


# =============================================================================
# Development Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
