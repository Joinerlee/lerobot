"""
LeRobot Backend S3 Storage Service

S3 영상 업로드 서비스.

Features:
- aioboto3 비동기 S3 클라이언트
- 멀티파트 업로드 지원 (대용량 파일)
- 업로드 진행률 추적
- 로컬 폴백 지원 (S3 미설정 시)

S3 Structure:
    s3://lerobot-teleoperation-data/
    └── sessions/
        └── {session_id}/
            └── {camera_key}_{timestamp}.mp4
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Callable

import aiofiles

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)



@dataclass
class UploadProgress:
    """업로드 진행률 추적."""

    total_bytes: int
    uploaded_bytes: int = 0
    parts_completed: int = 0
    total_parts: int = 0
    status: str = "pending"  # pending, uploading, completed, failed
    error: str | None = None
    s3_key: str | None = None
    local_path: str | None = None

    @property
    def percentage(self) -> float:
        """업로드 진행률 (0-100)."""
        if self.total_bytes == 0:
            return 0.0
        return (self.uploaded_bytes / self.total_bytes) * 100


@dataclass
class UploadResult:
    """업로드 결과."""

    success: bool
    storage_type: str  # "s3" or "local"
    path: str  # S3 URI or local path
    size: int
    duration_ms: float
    error: str | None = None


class S3StorageService:
    """S3 영상 스토리지 서비스.

    S3 설정이 없으면 로컬 파일시스템으로 폴백합니다.

    Usage:
        service = S3StorageService()

        # 단순 업로드
        result = await service.upload_video(
            content=video_bytes,
            session_id=1,
            camera_key="laptop",
            timestamp=1234567890.0
        )

        # 진행률 콜백과 함께
        async def on_progress(p: UploadProgress):
            print(f"Upload: {p.percentage:.1f}%")

        result = await service.upload_video(
            content=video_bytes,
            session_id=1,
            camera_key="laptop",
            timestamp=1234567890.0,
            progress_callback=on_progress
        )
    """

    def __init__(self):
        self._s3_available: bool | None = None
        self._client = None

    @property
    def s3_configured(self) -> bool:
        """S3 자격증명이 설정되었는지 확인."""
        return bool(
            settings.AWS_ACCESS_KEY_ID
            and settings.AWS_SECRET_ACCESS_KEY
            and settings.S3_BUCKET_NAME
        )

    async def _get_s3_client(self):
        """S3 클라이언트 가져오기 (lazy initialization)."""
        if self._client is None:
            try:
                import aioboto3

                session = aioboto3.Session(
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_REGION,
                )

                # 커스텀 엔드포인트 지원 (MinIO, LocalStack 등)
                client_kwargs = {}
                if settings.S3_ENDPOINT_URL:
                    client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL

                self._client = await session.client("s3", **client_kwargs).__aenter__()
                self._s3_available = True
                logger.info(
                    "S3 클라이언트 초기화",
                    bucket=settings.S3_BUCKET_NAME,
                    region=settings.AWS_REGION,
                    endpoint=settings.S3_ENDPOINT_URL or "AWS Default",
                )
            except ImportError:
                logger.warning("aioboto3 패키지 미설치, 로컬 스토리지로 폴백")
                self._s3_available = False
            except Exception as e:
                logger.error("S3 클라이언트 초기화 실패", error=str(e))
                self._s3_available = False
        return self._client

    def _generate_s3_key(
        self, session_id: int, camera_key: str, timestamp: float
    ) -> str:
        """S3 오브젝트 키 생성.

        Format: sessions/{session_id}/{camera_key}_{timestamp}.mp4
        """
        return f"sessions/{session_id}/{camera_key}_{int(timestamp)}.mp4"

    def _generate_local_path(
        self, session_id: int, camera_key: str, timestamp: float
    ) -> Path:
        """로컬 저장 경로 생성."""
        filename = f"{session_id}_{camera_key}_{int(timestamp)}.mp4"
        return settings.backup_path / "videos" / filename

    async def upload_video(
        self,
        content: bytes,
        session_id: int,
        camera_key: str,
        timestamp: float,
        progress_callback: Callable[[UploadProgress], Any] | None = None,
    ) -> UploadResult:
        """영상 파일 업로드.

        S3가 설정되어 있으면 S3로, 아니면 로컬로 저장합니다.

        Args:
            content: 영상 바이너리 데이터
            session_id: 세션 ID
            camera_key: 카메라 식별자
            timestamp: 영상 시작 타임스탬프
            progress_callback: 진행률 콜백 함수

        Returns:
            UploadResult with success status and path
        """
        import time

        start_time = time.perf_counter()
        content_size = len(content)

        # S3 사용 가능 여부 확인
        if self.s3_configured:
            await self._get_s3_client()

        if self._s3_available:
            result = await self._upload_to_s3(
                content=content,
                session_id=session_id,
                camera_key=camera_key,
                timestamp=timestamp,
                progress_callback=progress_callback,
            )
        else:
            result = await self._upload_to_local(
                content=content,
                session_id=session_id,
                camera_key=camera_key,
                timestamp=timestamp,
                progress_callback=progress_callback,
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "영상 업로드 완료",
            session_id=session_id,
            camera_key=camera_key,
            storage_type=result.storage_type,
            size_kb=round(content_size / 1024, 2),
            duration_ms=round(elapsed_ms, 2),
            success=result.success,
        )

        return UploadResult(
            success=result.success,
            storage_type=result.storage_type,
            path=result.path,
            size=content_size,
            duration_ms=elapsed_ms,
            error=result.error,
        )

    async def _upload_to_s3(
        self,
        content: bytes,
        session_id: int,
        camera_key: str,
        timestamp: float,
        progress_callback: Callable[[UploadProgress], Any] | None = None,
    ) -> UploadResult:
        """S3에 업로드."""
        s3_key = self._generate_s3_key(session_id, camera_key, timestamp)
        content_size = len(content)

        progress = UploadProgress(
            total_bytes=content_size,
            status="uploading",
            s3_key=s3_key,
        )

        try:
            # 멀티파트 업로드 필요 여부 확인
            if content_size >= settings.S3_MULTIPART_THRESHOLD:
                await self._multipart_upload(
                    content=content,
                    s3_key=s3_key,
                    progress=progress,
                    progress_callback=progress_callback,
                )
            else:
                # 단순 업로드
                await self._client.put_object(
                    Bucket=settings.S3_BUCKET_NAME,
                    Key=s3_key,
                    Body=content,
                    ContentType="video/mp4",
                )
                progress.uploaded_bytes = content_size
                progress.status = "completed"

                if progress_callback:
                    await self._call_progress_callback(progress_callback, progress)

            s3_uri = f"s3://{settings.S3_BUCKET_NAME}/{s3_key}"

            return UploadResult(
                success=True,
                storage_type="s3",
                path=s3_uri,
                size=content_size,
                duration_ms=0,  # 호출자가 설정
            )

        except Exception as e:
            logger.error(
                "S3 업로드 실패",
                s3_key=s3_key,
                error=str(e),
                exc_info=True,
            )
            progress.status = "failed"
            progress.error = str(e)

            if progress_callback:
                await self._call_progress_callback(progress_callback, progress)

            return UploadResult(
                success=False,
                storage_type="s3",
                path="",
                size=content_size,
                duration_ms=0,
                error=str(e),
            )

    async def _multipart_upload(
        self,
        content: bytes,
        s3_key: str,
        progress: UploadProgress,
        progress_callback: Callable[[UploadProgress], Any] | None = None,
    ) -> None:
        """멀티파트 업로드 수행."""
        content_size = len(content)
        chunk_size = settings.S3_MULTIPART_CHUNK_SIZE

        # 파트 수 계산
        num_parts = (content_size + chunk_size - 1) // chunk_size
        progress.total_parts = num_parts

        # 멀티파트 업로드 시작
        mpu = await self._client.create_multipart_upload(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
            ContentType="video/mp4",
        )
        upload_id = mpu["UploadId"]

        parts = []

        try:
            for part_num in range(1, num_parts + 1):
                start = (part_num - 1) * chunk_size
                end = min(start + chunk_size, content_size)
                chunk = content[start:end]

                # 파트 업로드
                response = await self._client.upload_part(
                    Bucket=settings.S3_BUCKET_NAME,
                    Key=s3_key,
                    UploadId=upload_id,
                    PartNumber=part_num,
                    Body=chunk,
                )

                parts.append({"ETag": response["ETag"], "PartNumber": part_num})

                # 진행률 업데이트
                progress.uploaded_bytes = end
                progress.parts_completed = part_num

                if progress_callback:
                    await self._call_progress_callback(progress_callback, progress)

            # 멀티파트 업로드 완료
            await self._client.complete_multipart_upload(
                Bucket=settings.S3_BUCKET_NAME,
                Key=s3_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )

            progress.status = "completed"

        except Exception:
            # 실패 시 멀티파트 업로드 중단
            await self._client.abort_multipart_upload(
                Bucket=settings.S3_BUCKET_NAME,
                Key=s3_key,
                UploadId=upload_id,
            )
            raise

    async def _upload_to_local(
        self,
        content: bytes,
        session_id: int,
        camera_key: str,
        timestamp: float,
        progress_callback: Callable[[UploadProgress], Any] | None = None,
    ) -> UploadResult:
        """로컬 파일시스템에 저장."""
        local_path = self._generate_local_path(session_id, camera_key, timestamp)
        content_size = len(content)

        progress = UploadProgress(
            total_bytes=content_size,
            status="uploading",
            local_path=str(local_path),
        )

        try:
            # 디렉토리 생성
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # 비동기 파일 쓰기
            async with aiofiles.open(local_path, "wb") as f:
                await f.write(content)

            progress.uploaded_bytes = content_size
            progress.status = "completed"

            if progress_callback:
                await self._call_progress_callback(progress_callback, progress)

            return UploadResult(
                success=True,
                storage_type="local",
                path=str(local_path),
                size=content_size,
                duration_ms=0,
            )

        except Exception as e:
            logger.error(
                "로컬 저장 실패",
                path=str(local_path),
                error=str(e),
                exc_info=True,
            )
            progress.status = "failed"
            progress.error = str(e)

            if progress_callback:
                await self._call_progress_callback(progress_callback, progress)

            return UploadResult(
                success=False,
                storage_type="local",
                path="",
                size=content_size,
                duration_ms=0,
                error=str(e),
            )

    async def _call_progress_callback(
        self,
        callback: Callable[[UploadProgress], Any],
        progress: UploadProgress,
    ) -> None:
        """진행률 콜백 호출."""
        try:
            result = callback(progress)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.warning("진행률 콜백 실패", error=str(e))

    async def check_s3_connection(self) -> dict[str, Any]:
        """S3 연결 상태 확인.

        Returns:
            dict with connection status and bucket info
        """
        if not self.s3_configured:
            return {
                "available": False,
                "reason": "S3 credentials not configured",
            }

        try:
            client = await self._get_s3_client()
            if client is None:
                return {
                    "available": False,
                    "reason": "Failed to create S3 client",
                }

            # 버킷 존재 확인
            await client.head_bucket(Bucket=settings.S3_BUCKET_NAME)

            return {
                "available": True,
                "bucket": settings.S3_BUCKET_NAME,
                "region": settings.AWS_REGION,
            }

        except Exception as e:
            return {
                "available": False,
                "reason": str(e),
            }

    async def close(self) -> None:
        """S3 클라이언트 종료."""
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
            logger.debug("S3 클라이언트 종료")


# 싱글톤 인스턴스
storage_service = S3StorageService()
