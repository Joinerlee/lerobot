"""
LeRobot Backend Telemetry Service

텔레오퍼레이션 데이터 버퍼링 및 배치 처리 서비스.

Performance Target:
- P95 < 10ms 프레임 처리
- 60 FPS × 50 로봇 = 3000 frames/sec 처리 가능
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..models import TeleopFrame

logger = get_logger(__name__)


@dataclass
class FrameData:
    """단일 프레임 데이터 구조."""
    session_id: int
    robot_id: str
    frame_index: int
    timestamp: float
    data: dict[str, Any]
    received_at: float = field(default_factory=time.perf_counter)


class TelemetryBuffer:
    """텔레오퍼레이션 데이터 버퍼.

    프레임을 메모리에 버퍼링하고, 설정된 크기에 도달하면
    배치로 DB에 INSERT합니다.

    Attributes:
        session_id: 연결된 세션 ID
        robot_id: 로봇 식별자
        buffer_size: 배치 크기 (기본: WS_BUFFER_SIZE)

    Usage:
        buffer = TelemetryBuffer(session_id=1, robot_id="robot-001")
        await buffer.add(frame_data)  # 자동으로 flush
        await buffer.flush_all(db)    # 연결 종료 시 잔여 데이터 저장

    Performance:
        - add(): O(1) 메모리 추가
        - flush(): 배치 INSERT로 DB 왕복 최소화
    """

    def __init__(
        self,
        session_id: int,
        robot_id: str,
        buffer_size: int | None = None,
    ):
        self.session_id = session_id
        self.robot_id = robot_id
        self.buffer_size = buffer_size or settings.WS_BUFFER_SIZE

        self._buffer: list[FrameData] = []
        self._total_frames: int = 0
        self._total_flush_count: int = 0
        self._lock = asyncio.Lock()

        # 성능 측정용
        self._processing_times: list[float] = []
        self._max_processing_times: int = 1000  # 최근 1000개 유지

        logger.debug(
            "TelemetryBuffer 생성",
            session_id=session_id,
            robot_id=robot_id,
            buffer_size=self.buffer_size,
        )

    @property
    def total_frames(self) -> int:
        """총 처리된 프레임 수."""
        return self._total_frames

    @property
    def pending_count(self) -> int:
        """버퍼에 대기 중인 프레임 수."""
        return len(self._buffer)

    @property
    def avg_processing_time_ms(self) -> float:
        """평균 처리 시간 (ms)."""
        if not self._processing_times:
            return 0.0
        return sum(self._processing_times) / len(self._processing_times) * 1000

    @property
    def p95_processing_time_ms(self) -> float:
        """P95 처리 시간 (ms)."""
        if not self._processing_times:
            return 0.0
        sorted_times = sorted(self._processing_times)
        idx = int(len(sorted_times) * 0.95)
        return sorted_times[min(idx, len(sorted_times) - 1)] * 1000

    async def add(
        self,
        frame_index: int,
        timestamp: float,
        data: dict[str, Any],
        db: AsyncSession,
    ) -> bool:
        """프레임 데이터를 버퍼에 추가.

        버퍼가 가득 차면 자동으로 flush합니다.

        Args:
            frame_index: 프레임 인덱스
            timestamp: 클라이언트 타임스탬프
            data: 관절값 데이터 (JSON)
            db: DB 세션

        Returns:
            True if flush 발생, False otherwise
        """
        start_time = time.perf_counter()

        frame = FrameData(
            session_id=self.session_id,
            robot_id=self.robot_id,
            frame_index=frame_index,
            timestamp=timestamp,
            data=data,
        )

        async with self._lock:
            self._buffer.append(frame)
            flushed = False

            if len(self._buffer) >= self.buffer_size:
                await self._flush(db)
                flushed = True

        # 처리 시간 기록
        elapsed = time.perf_counter() - start_time
        self._record_processing_time(elapsed)

        return flushed

    async def flush_all(self, db: AsyncSession) -> int:
        """버퍼의 모든 데이터를 DB에 저장.

        연결 종료 시 호출하여 잔여 데이터를 저장합니다.

        Args:
            db: DB 세션

        Returns:
            저장된 프레임 수
        """
        async with self._lock:
            if not self._buffer:
                return 0
            return await self._flush(db)

    async def _flush(self, db: AsyncSession) -> int:
        """내부 flush 로직 (lock 내부에서 호출).

        Returns:
            저장된 프레임 수
        """
        if not self._buffer:
            return 0

        flush_start = time.perf_counter()
        frames_to_save = self._buffer.copy()
        self._buffer.clear()

        # ORM 객체 생성
        import datetime
        db_frames = [
            TeleopFrame(
                session_id=f.session_id,
                robot_id=f.robot_id,
                frame_index=f.frame_index,
                timestamp=datetime.datetime.fromtimestamp(f.timestamp),
                data=f.data,
            )
            for f in frames_to_save
        ]

        # 배치 INSERT
        db.add_all(db_frames)
        await db.commit()

        count = len(frames_to_save)
        self._total_frames += count
        self._total_flush_count += 1

        flush_elapsed = time.perf_counter() - flush_start

        logger.debug(
            "프레임 배치 저장",
            session_id=self.session_id,
            robot_id=self.robot_id,
            batch_count=count,
            total_frames=self._total_frames,
            flush_time_ms=round(flush_elapsed * 1000, 2),
        )

        return count

    def _record_processing_time(self, elapsed: float) -> None:
        """처리 시간 기록 (메트릭용)."""
        self._processing_times.append(elapsed)
        # 최근 N개만 유지
        if len(self._processing_times) > self._max_processing_times:
            self._processing_times = self._processing_times[-self._max_processing_times:]

    def get_metrics(self) -> dict[str, Any]:
        """성능 메트릭 반환 (Prometheus 연동용).

        Returns:
            dict with performance metrics
        """
        return {
            "session_id": self.session_id,
            "robot_id": self.robot_id,
            "total_frames": self._total_frames,
            "pending_frames": len(self._buffer),
            "flush_count": self._total_flush_count,
            "avg_processing_time_ms": round(self.avg_processing_time_ms, 3),
            "p95_processing_time_ms": round(self.p95_processing_time_ms, 3),
        }


class TelemetryManager:
    """다중 로봇 텔레메트리 관리자.

    여러 로봇의 TelemetryBuffer를 관리하고 전체 메트릭을 집계합니다.
    """

    def __init__(self):
        self._buffers: dict[str, TelemetryBuffer] = {}
        self._lock = asyncio.Lock()

    async def get_or_create_buffer(
        self,
        session_id: int,
        robot_id: str,
    ) -> TelemetryBuffer:
        """로봇별 버퍼 조회 또는 생성."""
        key = f"{robot_id}:{session_id}"
        async with self._lock:
            if key not in self._buffers:
                self._buffers[key] = TelemetryBuffer(
                    session_id=session_id,
                    robot_id=robot_id,
                )
            return self._buffers[key]

    async def remove_buffer(self, session_id: int, robot_id: str) -> None:
        """버퍼 제거 (세션 종료 시)."""
        key = f"{robot_id}:{session_id}"
        async with self._lock:
            if key in self._buffers:
                del self._buffers[key]

    def get_all_metrics(self) -> list[dict[str, Any]]:
        """모든 버퍼의 메트릭 반환."""
        return [buf.get_metrics() for buf in self._buffers.values()]

    @property
    def active_buffer_count(self) -> int:
        """활성 버퍼 수."""
        return len(self._buffers)


# 싱글톤 인스턴스
telemetry_manager = TelemetryManager()
