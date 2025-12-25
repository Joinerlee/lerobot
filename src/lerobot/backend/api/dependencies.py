"""
LeRobot Backend API Dependencies

FastAPI dependency injection functions.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Header, WebSocket, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database import AsyncSessionLocal

logger = get_logger(__name__)

# API Key 헤더 스키마
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_db() -> AsyncSession:
    """비동기 DB 세션 생성기 (FastAPI Depends용).

    Yields:
        AsyncSession: SQLAlchemy 비동기 세션

    Example:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        yield session


async def verify_api_key(
    api_key: Optional[str] = Depends(api_key_header),
) -> Optional[str]:
    """HTTP 요청의 API Key를 검증합니다.

    API_KEY 환경변수가 설정되지 않은 경우 인증을 건너뜁니다.

    Args:
        api_key: X-API-Key 헤더 값

    Returns:
        검증된 API Key 또는 None (인증 비활성화 시)

    Raises:
        HTTPException: API Key가 없거나 유효하지 않은 경우 401
    """
    # API_KEY가 설정되지 않은 경우 인증 비활성화
    if not settings.API_KEY:
        return None

    if not api_key:
        logger.warning("API Key 누락", path="HTTP request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if api_key != settings.API_KEY:
        logger.warning("잘못된 API Key", provided_key_prefix=api_key[:8] + "..." if len(api_key) > 8 else "***")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key


async def verify_ws_api_key(
    websocket: WebSocket,
    api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Optional[str]:
    """WebSocket 연결의 API Key를 검증합니다.

    WebSocket은 Depends를 사용할 수 없어 직접 헤더를 추출합니다.
    쿼리 파라미터로도 API Key를 받을 수 있습니다.

    Args:
        websocket: WebSocket 연결
        api_key: X-API-Key 헤더 값

    Returns:
        검증된 API Key 또는 None (인증 비활성화 시)

    Raises:
        WebSocketException: API Key가 없거나 유효하지 않은 경우
    """
    # API_KEY가 설정되지 않은 경우 인증 비활성화
    if not settings.API_KEY:
        return None

    # 헤더에서 가져오기 시도
    if not api_key:
        api_key = websocket.headers.get("X-API-Key")

    # 쿼리 파라미터에서 가져오기 시도
    if not api_key:
        api_key = websocket.query_params.get("api_key")

    if not api_key:
        logger.warning("WebSocket API Key 누락", path=websocket.url.path)
        await websocket.close(code=4001, reason="API Key required")
        raise HTTPException(status_code=401, detail="API Key required")

    if api_key != settings.API_KEY:
        logger.warning("WebSocket 잘못된 API Key", path=websocket.url.path)
        await websocket.close(code=4003, reason="Invalid API Key")
        raise HTTPException(status_code=401, detail="Invalid API Key")

    return api_key


def require_api_key():
    """API Key 인증이 필요한 라우터용 의존성.

    Example:
        router = APIRouter(dependencies=[Depends(require_api_key())])
    """
    return Depends(verify_api_key)
