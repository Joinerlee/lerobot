"""
LeRobot Backend Health Check Routes

서버 및 의존성 상태 확인 엔드포인트.
"""

import datetime
from typing import Optional

from fastapi import APIRouter
from sqlalchemy import text

from ...core.config import settings
from ...core.logging import get_logger
from ...database import AsyncSessionLocal

logger = get_logger(__name__)
router = APIRouter(tags=["Health"])


async def check_database() -> dict:
    """데이터베이스 연결 상태 확인."""
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "healthy", "type": "sqlite" if settings.is_sqlite else "postgresql"}
    except Exception as e:
        logger.error("DB 헬스체크 실패", error=str(e))
        return {"status": "unhealthy", "error": str(e)}


async def check_redis() -> Optional[dict]:
    """Redis 연결 상태 확인 (설정된 경우만)."""
    if not settings.REDIS_URL:
        return None

    try:
        import redis.asyncio as redis
        client = redis.from_url(settings.REDIS_URL)
        await client.ping()
        await client.close()
        return {"status": "healthy"}
    except ImportError:
        return {"status": "not_installed", "message": "redis package not installed"}
    except Exception as e:
        logger.error("Redis 헬스체크 실패", error=str(e))
        return {"status": "unhealthy", "error": str(e)}


async def check_s3() -> Optional[dict]:
    """S3 버킷 접근 상태 확인 (AWS 자격증명 설정된 경우만)."""
    if not settings.AWS_ACCESS_KEY_ID:
        return None

    try:
        import aioboto3
        session = aioboto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        async with session.client("s3") as s3:
            await s3.head_bucket(Bucket=settings.S3_BUCKET_NAME)
        return {"status": "healthy", "bucket": settings.S3_BUCKET_NAME}
    except ImportError:
        return {"status": "not_installed", "message": "aioboto3 package not installed"}
    except Exception as e:
        logger.error("S3 헬스체크 실패", error=str(e))
        return {"status": "unhealthy", "error": str(e)}


@router.get("/health")
async def health_check():
    """간단한 헬스체크 (빠른 응답용).

    Returns:
        dict: 서버 상태와 현재 시간
    """
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat()
    }


@router.get("/health/detail")
async def health_check_detail():
    """상세 헬스체크 (모든 의존성 확인).

    DB, Redis, S3 등 모든 외부 의존성 상태를 확인합니다.

    Returns:
        dict: 종합 상태 및 각 서비스 상태
    """
    # 병렬로 모든 체크 실행
    db_status = await check_database()
    redis_status = await check_redis()
    s3_status = await check_s3()

    # 종합 상태 결정
    checks = [db_status]
    if redis_status:
        checks.append(redis_status)
    if s3_status:
        checks.append(s3_status)

    all_healthy = all(c.get("status") == "healthy" for c in checks)

    response = {
        "status": "healthy" if all_healthy else "degraded",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "version": settings.APP_VERSION,
        "services": {
            "database": db_status,
        }
    }

    if redis_status:
        response["services"]["redis"] = redis_status
    if s3_status:
        response["services"]["s3"] = s3_status

    return response


@router.get("/health/ready")
async def readiness_check():
    """준비 상태 체크 (Kubernetes readiness probe용).

    데이터베이스 연결이 정상인 경우만 healthy 반환.
    """
    db_status = await check_database()

    if db_status.get("status") == "healthy":
        return {"status": "ready"}
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Database not ready")


@router.get("/health/live")
async def liveness_check():
    """생존 상태 체크 (Kubernetes liveness probe용).

    서버가 응답 가능한지만 확인 (외부 의존성 무관).
    """
    return {"status": "alive"}
