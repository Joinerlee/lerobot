"""
LeRobot Backend Robot Routes

로봇 조회 및 상태 확인 엔드포인트.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ...database import AsyncSessionLocal
from ...models import TeleopSession
from ...services.connection import manager

router = APIRouter(tags=["Robots"])


@router.get("/robots")
async def get_robots():
    """연결된 적 있는 모든 로봇 목록을 조회합니다 (세션 기반).

    Returns:
        dict: 로봇 ID 목록, 총 개수, 현재 활성 연결 수
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TeleopSession.robot_id).distinct()
        )
        robot_ids = [row[0] for row in result.fetchall()]

    return {
        "robots": robot_ids,
        "count": len(robot_ids),
        "active_connections": manager.connection_count
    }


@router.get("/robots/{robot_id}/status")
async def get_robot_status(robot_id: str):
    """특정 로봇의 상태와 세션 히스토리를 조회합니다.

    Args:
        robot_id: 조회할 로봇 ID

    Returns:
        dict: 로봇 ID, 총 세션 수, 최근 세션 목록

    Raises:
        HTTPException: 로봇을 찾을 수 없는 경우 404
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TeleopSession)
            .where(TeleopSession.robot_id == robot_id)
            .order_by(TeleopSession.start_time.desc())
            .limit(10)  # 최근 10개 세션만
        )
        sessions = result.scalars().all()

    if not sessions:
        raise HTTPException(
            status_code=404,
            detail=f"로봇 '{robot_id}'을(를) 찾을 수 없습니다"
        )

    return {
        "robot_id": robot_id,
        "total_sessions": len(sessions),
        "recent_sessions": [
            {
                "id": s.id,
                "start_time": s.start_time.isoformat() if s.start_time else None,
                "fps": s.fps
            }
            for s in sessions
        ]
    }
