import asyncio
import json
import datetime
import os
import aiofiles
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .database import engine, get_db, AsyncSessionLocal
from .models import Base, TeleopSession, TeleopFrame, VideoChunk
from contextlib import asynccontextmanager

# 파일 저장 경로 (환경변수로 오버라이드 가능)
BACKUP_DIR = Path(os.getenv("LEROBOT_BACKUP_DIR", "./lerobot_backup"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB (create tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Ensure backup directory exists
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    yield

app = FastAPI(
    title="LeRobot Backend",
    description="Teleoperation data collection and dataset management API",
    version="0.1.0",
    lifespan=lifespan
)

# 성능 최적화: 버퍼링 설정
# 60프레임(약 1초)마다 DB에 한 번에 씁니다. (DB 부하 감소)
BUFFER_SIZE = 60 

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

manager = ConnectionManager()

@app.websocket("/ws/log/{robot_id}")
async def websocket_endpoint(websocket: WebSocket, robot_id: str):
    await manager.connect(websocket)
    
    # 이 연결을 위한 새로운 세션(Session) 생성
    session_db = AsyncSessionLocal()
    new_session = TeleopSession(robot_id=robot_id, fps=60) # 기본 60FPS
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
                timestamp=datetime.datetime.fromtimestamp(json_data.get("timestamp", 0)),
                data=json_data
            )
            buffer.append(frame_entry)
            
            # 비동기 배치 처리 (Buffer가 차면 DB에 저장)
            if len(buffer) >= BUFFER_SIZE:
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
        print(f"Error: {e}")
    finally:
        await session_db.close()


# 파일 업로드 엔드포인트 추가
@app.post("/upload/sync")
async def upload_sync(
    file: UploadFile = File(...),
    dataset_name: str = Form(...),
    relative_path: str = Form(...)
):
    """
    sync_service.py에서 전송한 데이터셋 파일(parquet, video)을 수신합니다.
    파일은 BACKUP_DIR/{dataset_name}/{relative_path} 경로에 저장됩니다.
    """
    try:
        # 저장 경로 생성
        save_path = BACKUP_DIR / dataset_name / relative_path
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # 비동기로 파일 저장
        async with aiofiles.open(save_path, 'wb') as f:
            content = await file.read()
            await f.write(content)

        return {"status": "success", "path": str(save_path), "size": len(content)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload/video")
async def upload_video(
    file: UploadFile = File(...),
    session_id: int = Form(...),
    camera_key: str = Form(...),
    start_timestamp: float = Form(...),
    end_timestamp: float = Form(...)
):
    """
    비디오 청크를 업로드하고 메타데이터를 DB에 기록합니다.
    텔레오퍼레이션 중 실시간 비디오 수집에 사용됩니다.
    """
    try:
        # 저장 경로 생성
        filename = f"{session_id}_{camera_key}_{int(start_timestamp)}.mp4"
        save_path = BACKUP_DIR / "videos" / filename
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # 파일 저장
        async with aiofiles.open(save_path, 'wb') as f:
            content = await file.read()
            await f.write(content)

        # DB에 메타데이터 기록
        async with AsyncSessionLocal() as db:
            video_chunk = VideoChunk(
                session_id=session_id,
                camera_key=camera_key,
                file_path=str(save_path),
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp
            )
            db.add(video_chunk)
            await db.commit()

        return {"status": "success", "path": str(save_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# 조회 엔드포인트
# =============================================================================

@app.get("/robots")
async def get_robots():
    """
    연결된 적 있는 모든 로봇 목록을 조회합니다 (세션 기반).
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TeleopSession.robot_id).distinct()
        )
        robot_ids = [row[0] for row in result.fetchall()]

    return {
        "robots": robot_ids,
        "count": len(robot_ids),
        "active_connections": len(manager.active_connections)  # 현재 활성 연결 수
    }


@app.get("/robots/{robot_id}/status")
async def get_robot_status(robot_id: str):
    """
    특정 로봇의 상태와 세션 히스토리를 조회합니다.
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
        raise HTTPException(status_code=404, detail=f"로봇 '{robot_id}'을(를) 찾을 수 없습니다")

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


@app.get("/sessions")
async def get_sessions(
    robot_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """
    텔레오퍼레이션 세션 목록을 조회합니다.
    robot_id로 필터링 가능합니다.
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


@app.get("/sessions/{session_id}")
async def get_session_detail(session_id: int):
    """
    특정 세션의 상세 정보를 조회합니다 (프레임 수, 비디오 정보 포함).
    """
    async with AsyncSessionLocal() as db:
        # 세션 조회
        result = await db.execute(
            select(TeleopSession).where(TeleopSession.id == session_id)
        )
        session = result.scalar_one_or_none()

        if not session:
            raise HTTPException(status_code=404, detail=f"세션 {session_id}을(를) 찾을 수 없습니다")

        # 프레임 수 카운트
        from sqlalchemy import func
        frame_count_result = await db.execute(
            select(func.count(TeleopFrame.id)).where(TeleopFrame.session_id == session_id)
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


@app.get("/health")
async def health_check():
    """서버 상태 확인용 헬스체크 엔드포인트."""
    return {"status": "healthy", "timestamp": datetime.datetime.utcnow().isoformat()}
