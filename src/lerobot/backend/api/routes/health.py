"""
LeRobot Backend Health Check Routes

서버 상태 확인 엔드포인트.
"""

import datetime

from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """서버 상태 확인용 헬스체크 엔드포인트.

    Returns:
        dict: 서버 상태와 현재 시간
    """
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
