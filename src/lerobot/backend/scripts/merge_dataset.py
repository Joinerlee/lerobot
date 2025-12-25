#!/usr/bin/env python3
"""
LeRobot 데이터 병합 스크립트

관절값(DB)과 영상(S3/로컬)을 병합하여 LeRobot 훈련 형식으로 변환합니다.

Usage:
    python -m scripts.merge_dataset --session_id 1 --repo_id user/dataset

Features:
    - S3/로컬 영상 다운로드
    - 타임스탬프 기반 프레임 매칭
    - LeRobot 데이터셋 형식 변환
    - 다중 카메라 지원
"""

import argparse
import asyncio
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from lerobot.backend.core.config import settings
from lerobot.backend.core.logging import get_logger
from lerobot.backend.models import TeleopFrame, TeleopSession, VideoChunk

logger = get_logger(__name__)


@dataclass
class MergeConfig:
    """병합 설정."""

    session_id: int
    repo_id: str
    output_dir: Path
    fps: int = 30
    max_timestamp_diff_ms: float = 50.0  # 최대 타임스탬프 차이 (밀리초)
    camera_keys: list[str] | None = None  # None이면 모든 카메라
    download_temp_dir: Path | None = None  # S3 다운로드 임시 디렉토리


@dataclass
class FrameData:
    """단일 프레임 데이터."""

    frame_index: int
    timestamp: float  # Unix timestamp
    observation: dict[str, float]
    action: dict[str, float]
    images: dict[str, np.ndarray] = field(default_factory=dict)  # camera_key → image


@dataclass
class MergeResult:
    """병합 결과."""

    success: bool
    total_frames: int
    matched_frames: int
    skipped_frames: int
    cameras: list[str]
    output_path: str
    duration_sec: float
    error: str | None = None


class VideoDownloader:
    """S3/로컬 영상 다운로더."""

    def __init__(self, temp_dir: Path | None = None):
        self._temp_dir = temp_dir or Path(tempfile.mkdtemp(prefix="lerobot_merge_"))
        self._s3_client = None

    async def _get_s3_client(self):
        """S3 클라이언트 가져오기."""
        if self._s3_client is None:
            try:
                import aioboto3

                session = aioboto3.Session(
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_REGION,
                )
                client_kwargs = {}
                if settings.S3_ENDPOINT_URL:
                    client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL

                self._s3_client = await session.client("s3", **client_kwargs).__aenter__()
            except ImportError:
                logger.warning("aioboto3 미설치, S3 다운로드 불가")
        return self._s3_client

    async def download(self, file_path: str) -> Path:
        """영상 파일 다운로드.

        Args:
            file_path: S3 URI (s3://bucket/key) 또는 로컬 경로

        Returns:
            다운로드된 로컬 파일 경로
        """
        if file_path.startswith("s3://"):
            return await self._download_from_s3(file_path)
        else:
            # 로컬 파일
            local_path = Path(file_path)
            if not local_path.exists():
                raise FileNotFoundError(f"로컬 파일 없음: {file_path}")
            return local_path

    async def _download_from_s3(self, s3_uri: str) -> Path:
        """S3에서 다운로드."""
        # Parse s3://bucket/key
        parts = s3_uri.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        local_path = self._temp_dir / Path(key).name
        local_path.parent.mkdir(parents=True, exist_ok=True)

        client = await self._get_s3_client()
        if client is None:
            raise RuntimeError("S3 클라이언트 초기화 실패")

        logger.info("S3 다운로드 시작", bucket=bucket, key=key)
        await client.download_file(bucket, key, str(local_path))
        logger.info("S3 다운로드 완료", local_path=str(local_path))

        return local_path

    async def close(self):
        """리소스 정리."""
        if self._s3_client:
            await self._s3_client.__aexit__(None, None, None)


class FrameExtractor:
    """비디오에서 프레임 추출."""

    def __init__(self, video_path: Path):
        self._video_path = video_path
        self._cap = cv2.VideoCapture(str(video_path))
        if not self._cap.isOpened():
            raise RuntimeError(f"비디오 열기 실패: {video_path}")

        self._fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._duration = self._total_frames / self._fps if self._fps > 0 else 0

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def total_frames(self) -> int:
        return self._total_frames

    @property
    def duration(self) -> float:
        return self._duration

    def extract_at_timestamp(
        self, target_timestamp: float, video_start_timestamp: float
    ) -> np.ndarray | None:
        """특정 타임스탬프의 프레임 추출.

        Args:
            target_timestamp: 추출할 프레임의 Unix 타임스탬프
            video_start_timestamp: 비디오 시작 타임스탬프

        Returns:
            RGB 이미지 numpy 배열 (또는 None)
        """
        # 비디오 내 상대 시간 계산
        relative_time = target_timestamp - video_start_timestamp
        if relative_time < 0 or relative_time > self._duration:
            return None

        # 프레임 인덱스 계산
        frame_idx = int(relative_time * self._fps)
        if frame_idx >= self._total_frames:
            return None

        # 프레임 위치로 이동
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self._cap.read()

        if not ret or frame is None:
            return None

        # BGR → RGB 변환
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def close(self):
        """비디오 리소스 해제."""
        self._cap.release()


class TimestampMatcher:
    """타임스탬프 기반 프레임 매칭."""

    def __init__(self, max_diff_ms: float = 50.0):
        self._max_diff_ms = max_diff_ms

    def find_closest_frame(
        self, target_timestamp: float, frame_timestamps: list[float]
    ) -> tuple[int, float] | None:
        """가장 가까운 프레임 인덱스 찾기.

        Args:
            target_timestamp: 찾을 타임스탬프
            frame_timestamps: 정렬된 프레임 타임스탬프 목록

        Returns:
            (인덱스, 차이_ms) 튜플 또는 None
        """
        if not frame_timestamps:
            return None

        # Binary search for closest
        left, right = 0, len(frame_timestamps) - 1
        closest_idx = 0
        min_diff = abs(frame_timestamps[0] - target_timestamp)

        while left <= right:
            mid = (left + right) // 2
            diff = abs(frame_timestamps[mid] - target_timestamp)

            if diff < min_diff:
                min_diff = diff
                closest_idx = mid

            if frame_timestamps[mid] < target_timestamp:
                left = mid + 1
            elif frame_timestamps[mid] > target_timestamp:
                right = mid - 1
            else:
                # 정확히 일치
                return (mid, 0.0)

        diff_ms = min_diff * 1000
        if diff_ms > self._max_diff_ms:
            return None

        return (closest_idx, diff_ms)


class DataMerger:
    """관절값과 영상 데이터 병합."""

    def __init__(self, config: MergeConfig):
        self._config = config
        self._engine = create_async_engine(settings.DATABASE_URL, echo=False)
        self._session_maker = sessionmaker(
            bind=self._engine, class_=AsyncSession, expire_on_commit=False
        )
        self._downloader = VideoDownloader(config.download_temp_dir)
        self._matcher = TimestampMatcher(config.max_timestamp_diff_ms)

    async def merge(self) -> MergeResult:
        """데이터 병합 수행."""
        start_time = time.perf_counter()

        try:
            async with self._session_maker() as db:
                # 1. 세션 정보 조회
                session_info = await self._get_session_info(db)
                if not session_info:
                    return MergeResult(
                        success=False,
                        total_frames=0,
                        matched_frames=0,
                        skipped_frames=0,
                        cameras=[],
                        output_path="",
                        duration_sec=0,
                        error=f"세션을 찾을 수 없습니다: {self._config.session_id}",
                    )

                # 2. 프레임 데이터 조회
                frames = await self._get_frames(db)
                if not frames:
                    return MergeResult(
                        success=False,
                        total_frames=0,
                        matched_frames=0,
                        skipped_frames=0,
                        cameras=[],
                        output_path="",
                        duration_sec=0,
                        error="프레임 데이터가 없습니다",
                    )

                # 3. 비디오 청크 조회
                video_chunks = await self._get_video_chunks(db)

                # 4. 비디오 다운로드 및 프레임 추출
                camera_extractors = await self._prepare_extractors(video_chunks)

                # 5. 데이터 병합
                merged_data = self._merge_frames(frames, video_chunks, camera_extractors)

                # 6. LeRobot 형식으로 내보내기
                output_path = await self._export_to_lerobot(
                    merged_data, session_info, list(camera_extractors.keys())
                )

                # 7. 리소스 정리
                for extractor in camera_extractors.values():
                    extractor.close()

                elapsed = time.perf_counter() - start_time
                matched = sum(1 for f in merged_data if f.images)
                skipped = len(merged_data) - matched

                return MergeResult(
                    success=True,
                    total_frames=len(frames),
                    matched_frames=matched,
                    skipped_frames=skipped,
                    cameras=list(camera_extractors.keys()),
                    output_path=output_path,
                    duration_sec=elapsed,
                )

        except Exception as e:
            logger.error("병합 실패", error=str(e), exc_info=True)
            return MergeResult(
                success=False,
                total_frames=0,
                matched_frames=0,
                skipped_frames=0,
                cameras=[],
                output_path="",
                duration_sec=time.perf_counter() - start_time,
                error=str(e),
            )
        finally:
            await self._downloader.close()

    async def _get_session_info(self, db: AsyncSession) -> TeleopSession | None:
        """세션 정보 조회."""
        result = await db.execute(
            select(TeleopSession).where(TeleopSession.id == self._config.session_id)
        )
        return result.scalar_one_or_none()

    async def _get_frames(self, db: AsyncSession) -> list[TeleopFrame]:
        """프레임 데이터 조회."""
        result = await db.execute(
            select(TeleopFrame)
            .where(TeleopFrame.session_id == self._config.session_id)
            .order_by(TeleopFrame.frame_index)
        )
        return list(result.scalars().all())

    async def _get_video_chunks(self, db: AsyncSession) -> list[VideoChunk]:
        """비디오 청크 조회."""
        query = select(VideoChunk).where(
            VideoChunk.session_id == self._config.session_id
        )

        if self._config.camera_keys:
            query = query.where(VideoChunk.camera_key.in_(self._config.camera_keys))

        result = await db.execute(query.order_by(VideoChunk.start_timestamp))
        return list(result.scalars().all())

    async def _prepare_extractors(
        self, video_chunks: list[VideoChunk]
    ) -> dict[str, FrameExtractor]:
        """카메라별 프레임 추출기 준비."""
        extractors = {}

        for chunk in video_chunks:
            if chunk.camera_key in extractors:
                continue  # 첫 번째 청크만 사용 (단순화)

            try:
                local_path = await self._downloader.download(chunk.file_path)
                extractors[chunk.camera_key] = FrameExtractor(local_path)
                logger.info(
                    "프레임 추출기 준비",
                    camera=chunk.camera_key,
                    fps=extractors[chunk.camera_key].fps,
                    frames=extractors[chunk.camera_key].total_frames,
                )
            except Exception as e:
                logger.warning(
                    "비디오 로드 실패",
                    camera=chunk.camera_key,
                    path=chunk.file_path,
                    error=str(e),
                )

        return extractors

    def _merge_frames(
        self,
        frames: list[TeleopFrame],
        video_chunks: list[VideoChunk],
        extractors: dict[str, FrameExtractor],
    ) -> list[FrameData]:
        """프레임 데이터 병합."""
        # 카메라별 비디오 시작 타임스탬프
        camera_start_times = {
            chunk.camera_key: chunk.start_timestamp for chunk in video_chunks
        }

        merged = []

        for frame in frames:
            # Unix timestamp 변환
            frame_timestamp = frame.timestamp.timestamp()

            frame_data = FrameData(
                frame_index=frame.frame_index,
                timestamp=frame_timestamp,
                observation=frame.data.get("observation", {}),
                action=frame.data.get("action", {}),
            )

            # 각 카메라에서 이미지 추출
            for camera_key, extractor in extractors.items():
                start_time = camera_start_times.get(camera_key, 0)
                image = extractor.extract_at_timestamp(frame_timestamp, start_time)
                if image is not None:
                    frame_data.images[camera_key] = image

            merged.append(frame_data)

        return merged

    async def _export_to_lerobot(
        self,
        frames: list[FrameData],
        session: TeleopSession,
        camera_keys: list[str],
    ) -> str:
        """LeRobot 형식으로 내보내기."""
        from lerobot.common.datasets.lerobot_dataset import LeRobotDataset

        if not frames:
            raise ValueError("내보낼 프레임이 없습니다")

        # Feature 정의
        first_frame = frames[0]
        features = {
            "observation.state": {
                "dtype": "float32",
                "shape": (len(first_frame.observation),),
                "names": list(first_frame.observation.keys()),
            },
            "action": {
                "dtype": "float32",
                "shape": (len(first_frame.action),),
                "names": list(first_frame.action.keys()),
            },
        }

        # 이미지 feature 추가
        use_videos = bool(camera_keys)
        if use_videos:
            for camera_key in camera_keys:
                features[f"observation.images.{camera_key}"] = {
                    "dtype": "video",
                    "shape": (480, 640, 3),  # TODO: 실제 해상도로 변경
                    "names": ["height", "width", "channel"],
                }

        # 데이터셋 생성
        output_path = self._config.output_dir / self._config.repo_id
        output_path.parent.mkdir(parents=True, exist_ok=True)

        dataset = LeRobotDataset.create(
            repo_id=self._config.repo_id,
            fps=session.fps or self._config.fps,
            features=features,
            robot_type=session.robot_id,
            root=str(self._config.output_dir),
            use_videos=use_videos,
        )

        # 프레임 추가
        for frame in frames:
            frame_dict = {
                "observation.state": torch.tensor(
                    list(frame.observation.values()), dtype=torch.float32
                ),
                "action": torch.tensor(
                    list(frame.action.values()), dtype=torch.float32
                ),
            }

            # 이미지 추가
            for camera_key in camera_keys:
                if camera_key in frame.images:
                    frame_dict[f"observation.images.{camera_key}"] = torch.from_numpy(
                        frame.images[camera_key]
                    )

            dataset.add_frame(frame_dict)

        # 저장
        dataset.save_episode()
        dataset.finalize()

        logger.info(
            "LeRobot 데이터셋 생성 완료",
            output_path=str(output_path),
            frames=len(frames),
            cameras=camera_keys,
        )

        return str(output_path)


async def main():
    """메인 함수."""
    parser = argparse.ArgumentParser(
        description="LeRobot 데이터 병합 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 기본 사용
    python -m scripts.merge_dataset --session_id 1 --repo_id user/dataset

    # 특정 카메라만 포함
    python -m scripts.merge_dataset --session_id 1 --repo_id user/dataset --cameras laptop phone

    # 출력 디렉토리 지정
    python -m scripts.merge_dataset --session_id 1 --repo_id user/dataset --output ./datasets
        """,
    )
    parser.add_argument(
        "--session_id",
        type=int,
        required=True,
        help="내보낼 세션 ID",
    )
    parser.add_argument(
        "--repo_id",
        type=str,
        required=True,
        help="Hugging Face 레포지토리 ID (예: user/dataset)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./lerobot_datasets",
        help="출력 디렉토리 (기본: ./lerobot_datasets)",
    )
    parser.add_argument(
        "--cameras",
        type=str,
        nargs="*",
        default=None,
        help="포함할 카메라 키 (기본: 모든 카메라)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="FPS (세션에 없으면 사용)",
    )
    parser.add_argument(
        "--max-diff-ms",
        type=float,
        default=50.0,
        help="최대 타임스탬프 차이 (밀리초)",
    )

    args = parser.parse_args()

    config = MergeConfig(
        session_id=args.session_id,
        repo_id=args.repo_id,
        output_dir=Path(args.output),
        fps=args.fps,
        max_timestamp_diff_ms=args.max_diff_ms,
        camera_keys=args.cameras,
    )

    print(f"\n{'='*60}")
    print("LeRobot 데이터 병합")
    print(f"{'='*60}")
    print(f"세션 ID: {config.session_id}")
    print(f"레포 ID: {config.repo_id}")
    print(f"출력 경로: {config.output_dir}")
    print(f"카메라: {config.camera_keys or '모든 카메라'}")
    print(f"{'='*60}\n")

    merger = DataMerger(config)
    result = await merger.merge()

    print(f"\n{'='*60}")
    print("병합 결과")
    print(f"{'='*60}")
    print(f"성공: {result.success}")
    print(f"총 프레임: {result.total_frames}")
    print(f"매칭된 프레임: {result.matched_frames}")
    print(f"스킵된 프레임: {result.skipped_frames}")
    print(f"카메라: {result.cameras}")
    print(f"소요 시간: {result.duration_sec:.2f}초")

    if result.success:
        print(f"출력 경로: {result.output_path}")
    else:
        print(f"오류: {result.error}")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
