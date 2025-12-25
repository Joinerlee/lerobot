"""
LeRobot Backend Upload Routes

파일 업로드 (데이터셋 동기화, 비디오) 엔드포인트.

Features:
- 로컬 파일 동기화 업로드
- S3 영상 업로드 (폴백: 로컬)
- 파일 크기/형식 검증
- 세션 유효성 확인
"""

import aiofiles
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from sqlalchemy import select

from ...core.config import settings
from ...core.logging import get_logger
from ...database import AsyncSessionLocal
from ...models import TeleopSession, VideoChunk
from ...services.storage import storage_service

logger = get_logger(__name__)
router = APIRouter(tags=["Upload"])


def _validate_video_file(filename: str, content_length: int | None) -> None:
    """비디오 파일 검증.

    Args:
        filename: 파일명
        content_length: 콘텐츠 길이 (bytes)

    Raises:
        HTTPException: 검증 실패 시
    """
    # 확장자 검증
    if not filename:
        raise HTTPException(status_code=400, detail="파일명이 필요합니다")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in settings.VIDEO_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않는 파일 형식: {ext}. 허용: {settings.VIDEO_ALLOWED_EXTENSIONS}",
        )

    # 파일 크기 검증 (Content-Length 헤더가 있는 경우)
    max_size = settings.VIDEO_MAX_SIZE_MB * 1024 * 1024
    if content_length and content_length > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"파일이 너무 큽니다. 최대: {settings.VIDEO_MAX_SIZE_MB}MB",
        )


async def _verify_session(session_id: int) -> TeleopSession:
    """세션 유효성 확인.

    Args:
        session_id: 확인할 세션 ID

    Returns:
        TeleopSession: 유효한 세션

    Raises:
        HTTPException: 세션이 없거나 이미 종료된 경우
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TeleopSession).where(TeleopSession.id == session_id)
        )
        session = result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"세션을 찾을 수 없습니다: {session_id}",
            )

        return session


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

        logger.info(
            "데이터셋 파일 업로드",
            dataset_name=dataset_name,
            relative_path=relative_path,
            size_kb=round(len(content) / 1024, 2),
        )

        return {
            "status": "success",
            "path": str(save_path),
            "size": len(content)
        }
    except Exception as e:
        logger.error(
            "데이터셋 파일 업로드 실패",
            dataset_name=dataset_name,
            relative_path=relative_path,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/video")
async def upload_video(
    file: UploadFile = File(...),
    session_id: int = Form(...),
    camera_key: str = Form(...),
    start_timestamp: float = Form(...),
    end_timestamp: float = Form(...)
):
    """비디오 파일을 S3 또는 로컬에 업로드합니다.

    S3 설정이 있으면 S3로, 없으면 로컬 파일시스템에 저장합니다.

    Args:
        file: 업로드할 비디오 파일
        session_id: 연결된 세션 ID
        camera_key: 카메라 식별자
        start_timestamp: 비디오 시작 타임스탬프
        end_timestamp: 비디오 종료 타임스탬프

    Returns:
        dict: 저장 상태, 스토리지 타입, 파일 경로

    Raises:
        HTTPException:
            - 400: 잘못된 파일 형식
            - 404: 세션 없음
            - 413: 파일 크기 초과
            - 500: 저장 실패
    """
    # 1. 파일 검증
    _validate_video_file(file.filename, file.size)

    # 2. 세션 유효성 확인
    session = await _verify_session(session_id)

    # 3. 파일 콘텐츠 읽기
    try:
        content = await file.read()
    except Exception as e:
        logger.error("파일 읽기 실패", error=str(e))
        raise HTTPException(status_code=500, detail="파일 읽기 실패")

    # 크기 재검증 (실제 콘텐츠 기반)
    max_size = settings.VIDEO_MAX_SIZE_MB * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"파일이 너무 큽니다. 최대: {settings.VIDEO_MAX_SIZE_MB}MB",
        )

    # 4. S3 또는 로컬에 업로드
    try:
        result = await storage_service.upload_video(
            content=content,
            session_id=session_id,
            camera_key=camera_key,
            timestamp=start_timestamp,
        )

        if not result.success:
            raise HTTPException(
                status_code=500,
                detail=f"업로드 실패: {result.error}",
            )

        # 5. DB에 메타데이터 기록
        async with AsyncSessionLocal() as db:
            video_chunk = VideoChunk(
                session_id=session_id,
                robot_id=session.robot_id,
                camera_key=camera_key,
                file_path=result.path,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
            )
            db.add(video_chunk)
            await db.commit()

        logger.info(
            "비디오 업로드 완료",
            session_id=session_id,
            camera_key=camera_key,
            storage_type=result.storage_type,
            path=result.path,
            size_mb=round(result.size / (1024 * 1024), 2),
            duration_ms=round(result.duration_ms, 2),
        )

        return {
            "status": "success",
            "storage_type": result.storage_type,
            "path": result.path,
            "size": result.size,
            "duration_ms": round(result.duration_ms, 2),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "비디오 업로드 실패",
            session_id=session_id,
            camera_key=camera_key,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/upload/storage-status")
async def get_storage_status():
    """스토리지 상태 확인.

    S3 연결 상태 및 설정 정보를 반환합니다.

    Returns:
        dict: S3 연결 상태, 버킷 정보, 로컬 백업 경로
    """
    s3_status = await storage_service.check_s3_connection()

    return {
        "s3": s3_status,
        "local": {
            "backup_dir": str(settings.backup_path),
            "exists": settings.backup_path.exists(),
        },
        "config": {
            "max_video_size_mb": settings.VIDEO_MAX_SIZE_MB,
            "allowed_extensions": settings.VIDEO_ALLOWED_EXTENSIONS,
            "multipart_threshold_mb": settings.S3_MULTIPART_THRESHOLD // (1024 * 1024),
        },
    }
