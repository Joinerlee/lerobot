import asyncio
import json
import datetime
import os
import aiofiles
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from .database import engine, Base, get_db, AsyncSessionLocal
from .models import TeleopSession, TeleopFrame, VideoChunk
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB (create tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(lifespan=lifespan)

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
