"""
LeRobot Backend WebSocket Routes

텔레오퍼레이션 데이터 실시간 수신 WebSocket 엔드포인트.
"""

import json
import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...core.config import settings
from ...core.logging import get_logger
from ...database import AsyncSessionLocal
from ...models import TeleopSession, TeleopFrame
from ...services.connection import manager
from ..dependencies import verify_ws_api_key

logger = get_logger(__name__)
router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/log/{robot_id}")
async def websocket_endpoint(websocket: WebSocket, robot_id: str):
    """텔레오퍼레이션 데이터를 실시간으로 수신하는 WebSocket 엔드포인트.

    연결 시 새 세션을 생성하고, 수신된 프레임 데이터를 버퍼링하여
    배치로 DB에 저장합니다.

    Args:
        websocket: WebSocket 연결
        robot_id: 연결하는 로봇 ID

    Protocol:
        - 연결 시: 새 TeleopSession 생성
        - 데이터 수신: JSON 형식의 프레임 데이터
        - 버퍼: WS_BUFFER_SIZE(기본 60)개마다 배치 INSERT
        - 연결 종료: 남은 버퍼 저장 후 정리

    Authentication:
        - API_KEY 환경변수 설정 시 인증 필요
        - X-API-Key 헤더 또는 ?api_key= 쿼리 파라미터
    """
    # API Key 인증 (설정된 경우)
    try:
        await verify_ws_api_key(websocket)
    except Exception:
        return  # 연결 이미 종료됨

    await manager.connect(websocket)
    logger.info("WebSocket 연결됨", robot_id=robot_id)

    # 이 연결을 위한 새로운 세션 생성
    session_db = AsyncSessionLocal()
    new_session = TeleopSession(robot_id=robot_id, fps=60)  # 기본 60FPS
    session_db.add(new_session)
    await session_db.commit()
    await session_db.refresh(new_session)
    session_id = new_session.id
    logger.info("텔레오퍼레이션 세션 생성", session_id=session_id, robot_id=robot_id)

    buffer = []
    total_frames = 0

    try:
        while True:
            data = await websocket.receive_text()
            json_data = json.loads(data)

            # 메모리에 프레임 객체 생성
            frame_entry = TeleopFrame(
                session_id=session_id,
                frame_index=json_data.get("frame_index"),
                timestamp=datetime.datetime.fromtimestamp(
                    json_data.get("timestamp", 0)
                ),
                data=json_data
            )
            buffer.append(frame_entry)

            # 비동기 배치 처리 (Buffer가 차면 DB에 저장)
            if len(buffer) >= settings.WS_BUFFER_SIZE:
                session_db.add_all(buffer)
                await session_db.commit()
                total_frames += len(buffer)
                buffer.clear()
                logger.debug("프레임 배치 저장", session_id=session_id, total_frames=total_frames)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        # 끊겼을 때 남은 데이터 저장
        if buffer:
            session_db.add_all(buffer)
            await session_db.commit()
            total_frames += len(buffer)
        logger.info("WebSocket 연결 종료", robot_id=robot_id, session_id=session_id, total_frames=total_frames)
    except Exception as e:
        logger.error("WebSocket 오류", robot_id=robot_id, session_id=session_id, error=str(e), exc_info=True)
    finally:
        await session_db.close()
