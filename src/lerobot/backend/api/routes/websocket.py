"""
LeRobot Backend WebSocket Routes

텔레오퍼레이션 데이터 실시간 수신 WebSocket 엔드포인트.

Performance:
- TelemetryBuffer로 배치 INSERT (60프레임/배치)
- P95 < 10ms 프레임 처리 목표
"""

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...core.logging import get_logger
from ...database import AsyncSessionLocal
from ...models import TeleopSession
from ...services.connection import manager
from ...services.telemetry import telemetry_manager
from ..dependencies import verify_ws_api_key

logger = get_logger(__name__)
router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/log/{robot_id}")
async def websocket_endpoint(websocket: WebSocket, robot_id: str):
    """텔레오퍼레이션 데이터를 실시간으로 수신하는 WebSocket 엔드포인트.

    연결 시 새 세션을 생성하고, TelemetryBuffer를 통해 프레임 데이터를
    배치로 DB에 저장합니다.

    Args:
        websocket: WebSocket 연결
        robot_id: 연결하는 로봇 ID

    Protocol:
        - 연결 시: 새 TeleopSession 생성 + TelemetryBuffer 할당
        - 데이터 수신: JSON 형식의 프레임 데이터
        - 버퍼: WS_BUFFER_SIZE(기본 60)개마다 배치 INSERT
        - 연결 종료: 남은 버퍼 저장 + 메트릭 로깅

    Authentication:
        - API_KEY 환경변수 설정 시 인증 필요
        - X-API-Key 헤더 또는 ?api_key= 쿼리 파라미터

    Performance:
        - TelemetryBuffer로 배치 처리
        - P95 < 10ms 프레임 처리 목표
    """
    # API Key 인증 (설정된 경우)
    try:
        await verify_ws_api_key(websocket)
    except Exception:
        return  # 연결 이미 종료됨

    await manager.connect(websocket)
    logger.info("WebSocket 연결됨", robot_id=robot_id)

    # DB 세션 및 텔레오퍼레이션 세션 생성
    session_db = AsyncSessionLocal()
    new_session = TeleopSession(robot_id=robot_id, fps=60)
    session_db.add(new_session)
    await session_db.commit()
    await session_db.refresh(new_session)
    session_id = new_session.id

    # TelemetryBuffer 생성
    buffer = await telemetry_manager.get_or_create_buffer(
        session_id=session_id,
        robot_id=robot_id,
    )

    logger.info(
        "텔레오퍼레이션 세션 생성",
        session_id=session_id,
        robot_id=robot_id,
        buffer_size=buffer.buffer_size,
    )

    try:
        while True:
            data = await websocket.receive_text()
            json_data = json.loads(data)

            # TelemetryBuffer에 프레임 추가 (자동 flush)
            await buffer.add(
                frame_index=json_data.get("frame_index", 0),
                timestamp=json_data.get("timestamp", 0),
                data=json_data,
                db=session_db,
            )

    except WebSocketDisconnect:
        manager.disconnect(websocket)

        # 잔여 데이터 저장
        remaining = await buffer.flush_all(session_db)
        metrics = buffer.get_metrics()

        logger.info(
            "WebSocket 연결 종료",
            robot_id=robot_id,
            session_id=session_id,
            total_frames=metrics["total_frames"],
            remaining_flushed=remaining,
            avg_processing_ms=metrics["avg_processing_time_ms"],
            p95_processing_ms=metrics["p95_processing_time_ms"],
        )

        # 버퍼 정리
        await telemetry_manager.remove_buffer(session_id, robot_id)

    except Exception as e:
        logger.error(
            "WebSocket 오류",
            robot_id=robot_id,
            session_id=session_id,
            error=str(e),
            exc_info=True,
        )
    finally:
        await session_db.close()
