"""
LeRobot Backend Upload Routes

파일 업로드 (데이터셋 동기화, 비디오) 엔드포인트.
"""

import aiofiles
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from ...core.config import settings
from ...database import AsyncSessionLocal
from ...models import VideoChunk

router = APIRouter(tags=["Upload"])


@router.post("/upload/sync")
async def upload_sync(
    file: UploadFile = File(...),
    dataset_name: str = Form(...),
    relative_path: str = Form(...)
):
    """sync_service.py에서 전송한 데이터셋 파일(parquet, video)을 수신합니다.

    파일은 BACKUP_DIR/{dataset_name}/{relative_path} 경로에 저장됩니다.

    Args:
        file: 업로드할 파일
        dataset_name: 데이터셋 이름
        relative_path: 데이터셋 내 상대 경로

    Returns:
        dict: 저장 상태, 경로, 파일 크기

    Raises:
        HTTPException: 저장 실패 시 500
    """
    try:
        # 저장 경로 생성
        save_path = settings.backup_path / dataset_name / relative_path
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # 비동기로 파일 저장
        async with aiofiles.open(save_path, 'wb') as f:
            content = await file.read()
            await f.write(content)

        return {
            "status": "success",
            "path": str(save_path),
            "size": len(content)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/video")
async def upload_video(
    file: UploadFile = File(...),
    session_id: int = Form(...),
    camera_key: str = Form(...),
    start_timestamp: float = Form(...),
    end_timestamp: float = Form(...)
):
    """비디오 청크를 업로드하고 메타데이터를 DB에 기록합니다.

    텔레오퍼레이션 중 실시간 비디오 수집에 사용됩니다.

    Args:
        file: 업로드할 비디오 파일
        session_id: 연결된 세션 ID
        camera_key: 카메라 식별자
        start_timestamp: 비디오 시작 타임스탬프
        end_timestamp: 비디오 종료 타임스탬프

    Returns:
        dict: 저장 상태, 파일 경로

    Raises:
        HTTPException: 저장 실패 시 500
    """
    try:
        # 저장 경로 생성
        filename = f"{session_id}_{camera_key}_{int(start_timestamp)}.mp4"
        save_path = settings.backup_path / "videos" / filename
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

        return {
            "status": "success",
            "path": str(save_path)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
