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

from fastapi import FastAPI

from .core.config import settings
from .database import engine
from .models import Base
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 백업 디렉토리 생성
    settings.backup_path.mkdir(parents=True, exist_ok=True)

    yield

    # Shutdown (필요 시 추가)


app = FastAPI(
    title=settings.APP_NAME,
    description="Teleoperation data collection and dataset management API",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# =============================================================================
# Router Registration
# =============================================================================

app.include_router(health_router)
app.include_router(robots_router)
app.include_router(sessions_router)
app.include_router(upload_router)
app.include_router(websocket_router)


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
