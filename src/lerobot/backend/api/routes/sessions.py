"""
LeRobot Backend Session Routes

텔레오퍼레이션 세션 CRUD 엔드포인트.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from ...database import AsyncSessionLocal
from ...models import TeleopSession, TeleopFrame, VideoChunk

router = APIRouter(tags=["Sessions"])


@router.get("/sessions")
async def get_sessions(
    robot_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """텔레오퍼레이션 세션 목록을 조회합니다.

    Args:
        robot_id: 필터링할 로봇 ID (선택)
        limit: 반환할 최대 세션 수
        offset: 건너뛸 세션 수

    Returns:
        dict: 세션 목록, 개수, limit, offset
    """
    async with AsyncSessionLocal() as db:
        query = select(TeleopSession).order_by(TeleopSession.start_time.desc())

        if robot_id:
            query = query.where(TeleopSession.robot_id == robot_id)

        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        sessions = result.scalars().all()

    return {
        "sessions": [
            {
                "id": s.id,
                "robot_id": s.robot_id,
                "start_time": s.start_time.isoformat() if s.start_time else None,
                "fps": s.fps,
                "meta_info": s.meta_info
            }
            for s in sessions
        ],
        "count": len(sessions),
        "limit": limit,
        "offset": offset
    }


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: int):
    """특정 세션의 상세 정보를 조회합니다 (프레임 수, 비디오 정보 포함).

    Args:
        session_id: 조회할 세션 ID

    Returns:
        dict: 세션 상세 정보 (프레임 수, 비디오 목록 포함)

    Raises:
        HTTPException: 세션을 찾을 수 없는 경우 404
    """
    async with AsyncSessionLocal() as db:
        # 세션 조회
        result = await db.execute(
            select(TeleopSession).where(TeleopSession.id == session_id)
        )
        session = result.scalar_one_or_none()

        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"세션 {session_id}을(를) 찾을 수 없습니다"
            )

        # 프레임 수 카운트
        frame_count_result = await db.execute(
            select(func.count(TeleopFrame.id))
            .where(TeleopFrame.session_id == session_id)
        )
        frame_count = frame_count_result.scalar()

        # 비디오 청크 조회
        video_result = await db.execute(
            select(VideoChunk).where(VideoChunk.session_id == session_id)
        )
        videos = video_result.scalars().all()

    return {
        "id": session.id,
        "robot_id": session.robot_id,
        "start_time": session.start_time.isoformat() if session.start_time else None,
        "fps": session.fps,
        "meta_info": session.meta_info,
        "frame_count": frame_count,
        "videos": [
            {
                "camera_key": v.camera_key,
                "file_path": v.file_path,
                "start_timestamp": v.start_timestamp,
                "end_timestamp": v.end_timestamp
            }
            for v in videos
        ]
    }
