"""
LeRobot Backend WebSocket Routes

텔레오퍼레이션 데이터 실시간 수신 WebSocket 엔드포인트.
"""

import json
import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...core.config import settings
from ...database import AsyncSessionLocal
from ...models import TeleopSession, TeleopFrame
from ...services.connection import manager

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
    """
    await manager.connect(websocket)

    # 이 연결을 위한 새로운 세션 생성
    session_db = AsyncSessionLocal()
    new_session = TeleopSession(robot_id=robot_id, fps=60)  # 기본 60FPS
    session_db.add(new_session)
    await session_db.commit()
    await session_db.refresh(new_session)
    session_id = new_session.id

    buffer = []

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
                buffer.clear()

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        # 끊겼을 때 남은 데이터 저장
        if buffer:
            session_db.add_all(buffer)
            await session_db.commit()
    except Exception as e:
        print(f"WebSocket Error: {e}")
    finally:
        await session_db.close()
