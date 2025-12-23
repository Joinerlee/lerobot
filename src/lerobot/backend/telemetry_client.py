"""
LeRobot Telemetry Client (텔레메트리 클라이언트)

이 모듈은 로봇의 실시간 데이터를 백엔드 서버로 전송합니다.
teleoperate.py 등에서 import하여 사용할 수 있습니다.

사용법:
    from lerobot.backend.telemetry_client import TelemetryClient

    # 동기 방식 (간단)
    client = TelemetryClient("ws://localhost:8000", "robot_A")
    client.connect()
    client.send_frame({"observation": {...}, "action": {...}})
    client.disconnect()

    # 비동기 방식 (권장)
    async with TelemetryClient("ws://localhost:8000", "robot_A") as client:
        await client.send_frame_async(data)
"""

import asyncio
import json
import time
import threading
import queue
from typing import Optional, Any
from dataclasses import dataclass, field
import os

# WebSocket 라이브러리 (설치 필요: pip install websockets)
try:
    import websockets
    from websockets.sync.client import connect as ws_connect
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    print("[TelemetryClient] 경고: websockets 라이브러리가 없습니다. pip install websockets")


@dataclass
class TelemetryStats:
    """텔레메트리 통계 정보"""
    frames_sent: int = 0
    frames_failed: int = 0
    bytes_sent: int = 0
    start_time: float = field(default_factory=time.time)
    last_send_time: float = 0.0

    @property
    def uptime(self) -> float:
        return time.time() - self.start_time

    @property
    def fps(self) -> float:
        if self.uptime > 0:
            return self.frames_sent / self.uptime
        return 0.0


class TelemetryClient:
    """
    로봇 텔레메트리 데이터를 백엔드로 전송하는 클라이언트.

    두 가지 모드 지원:
    1. 동기 모드: connect() -> send_frame() -> disconnect()
    2. 비동기 모드: async with TelemetryClient() as client: await client.send_frame_async()

    Args:
        backend_url: 백엔드 서버 URL (예: "ws://localhost:8000" 또는 "http://localhost:8000")
        robot_id: 로봇 식별자
        auto_reconnect: 연결 끊김 시 자동 재연결 여부
        buffer_size: 전송 대기 버퍼 크기 (0이면 무제한)
    """

    def __init__(
        self,
        backend_url: str = None,
        robot_id: str = "default_robot",
        auto_reconnect: bool = True,
        buffer_size: int = 1000
    ):
        # 환경변수로 기본값 설정
        if backend_url is None:
            backend_url = os.getenv("LEROBOT_BACKEND_URL", "ws://localhost:8000")

        # HTTP URL을 WebSocket URL로 변환
        if backend_url.startswith("http://"):
            backend_url = backend_url.replace("http://", "ws://")
        elif backend_url.startswith("https://"):
            backend_url = backend_url.replace("https://", "wss://")

        self.backend_url = backend_url
        self.robot_id = robot_id
        self.auto_reconnect = auto_reconnect
        self.buffer_size = buffer_size

        # 연결 상태
        self._ws = None
        self._ws_async = None
        self._connected = False
        self._frame_index = 0

        # 비동기 전송용 큐 및 스레드
        self._send_queue: queue.Queue = queue.Queue(maxsize=buffer_size if buffer_size > 0 else 0)
        self._sender_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 통계
        self.stats = TelemetryStats()

    @property
    def ws_url(self) -> str:
        """WebSocket 엔드포인트 전체 URL"""
        return f"{self.backend_url}/ws/log/{self.robot_id}"

    @property
    def connected(self) -> bool:
        return self._connected

    # =========================================================================
    # 동기 API (Synchronous API)
    # =========================================================================

    def connect(self) -> bool:
        """
        백엔드 서버에 연결합니다 (동기).

        Returns:
            연결 성공 여부
        """
        if not WEBSOCKETS_AVAILABLE:
            print("[TelemetryClient] websockets 라이브러리가 필요합니다")
            return False

        try:
            self._ws = ws_connect(self.ws_url)
            self._connected = True
            self._frame_index = 0
            self.stats = TelemetryStats()
            print(f"[TelemetryClient] 연결 성공: {self.ws_url}")
            return True
        except Exception as e:
            print(f"[TelemetryClient] 연결 실패: {e}")
            self._connected = False
            return False

    def disconnect(self):
        """백엔드 서버 연결을 종료합니다."""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False
        print(f"[TelemetryClient] 연결 종료 (전송: {self.stats.frames_sent} 프레임)")

    def send_frame(self, data: dict) -> bool:
        """
        프레임 데이터를 전송합니다 (동기, 블로킹).

        Args:
            data: 전송할 데이터 (observation, action 등)

        Returns:
            전송 성공 여부
        """
        if not self._connected or not self._ws:
            if self.auto_reconnect:
                self.connect()
            if not self._connected:
                return False

        # 프레임 메타데이터 추가
        frame_data = {
            "frame_index": self._frame_index,
            "timestamp": time.time(),
            **data
        }

        try:
            message = json.dumps(frame_data)
            self._ws.send(message)

            # 통계 업데이트
            self._frame_index += 1
            self.stats.frames_sent += 1
            self.stats.bytes_sent += len(message)
            self.stats.last_send_time = time.time()
            return True

        except Exception as e:
            print(f"[TelemetryClient] 전송 실패: {e}")
            self.stats.frames_failed += 1
            self._connected = False

            if self.auto_reconnect:
                self.connect()
            return False

    # =========================================================================
    # 비동기 API (Asynchronous API)
    # =========================================================================

    async def connect_async(self) -> bool:
        """백엔드 서버에 연결합니다 (비동기)."""
        if not WEBSOCKETS_AVAILABLE:
            print("[TelemetryClient] websockets 라이브러리가 필요합니다")
            return False

        try:
            self._ws_async = await websockets.connect(self.ws_url)
            self._connected = True
            self._frame_index = 0
            self.stats = TelemetryStats()
            print(f"[TelemetryClient] 비동기 연결 성공: {self.ws_url}")
            return True
        except Exception as e:
            print(f"[TelemetryClient] 비동기 연결 실패: {e}")
            self._connected = False
            return False

    async def disconnect_async(self):
        """백엔드 서버 연결을 종료합니다 (비동기)."""
        if self._ws_async:
            try:
                await self._ws_async.close()
            except Exception:
                pass
            self._ws_async = None
        self._connected = False

    async def send_frame_async(self, data: dict) -> bool:
        """프레임 데이터를 전송합니다 (비동기)."""
        if not self._connected or not self._ws_async:
            if self.auto_reconnect:
                await self.connect_async()
            if not self._connected:
                return False

        frame_data = {
            "frame_index": self._frame_index,
            "timestamp": time.time(),
            **data
        }

        try:
            message = json.dumps(frame_data)
            await self._ws_async.send(message)

            self._frame_index += 1
            self.stats.frames_sent += 1
            self.stats.bytes_sent += len(message)
            self.stats.last_send_time = time.time()
            return True

        except Exception as e:
            print(f"[TelemetryClient] 비동기 전송 실패: {e}")
            self.stats.frames_failed += 1
            self._connected = False
            return False

    # =========================================================================
    # 백그라운드 전송 모드 (Non-blocking)
    # =========================================================================

    def start_background_sender(self):
        """
        백그라운드 전송 스레드를 시작합니다.
        queue_frame()으로 데이터를 큐에 넣으면 별도 스레드에서 전송합니다.
        """
        if self._sender_thread and self._sender_thread.is_alive():
            return

        self._stop_event.clear()
        self._sender_thread = threading.Thread(target=self._background_sender_loop, daemon=True)
        self._sender_thread.start()
        print("[TelemetryClient] 백그라운드 전송 스레드 시작")

    def stop_background_sender(self):
        """백그라운드 전송 스레드를 중지합니다."""
        self._stop_event.set()
        if self._sender_thread:
            self._sender_thread.join(timeout=2.0)
        self.disconnect()
        print("[TelemetryClient] 백그라운드 전송 스레드 종료")

    def queue_frame(self, data: dict) -> bool:
        """
        프레임을 전송 큐에 추가합니다 (논블로킹).
        백그라운드 스레드가 큐에서 꺼내서 전송합니다.

        Returns:
            큐 추가 성공 여부 (큐가 가득 차면 False)
        """
        try:
            self._send_queue.put_nowait(data)
            return True
        except queue.Full:
            self.stats.frames_failed += 1
            return False

    def _background_sender_loop(self):
        """백그라운드 전송 스레드의 메인 루프"""
        self.connect()

        while not self._stop_event.is_set():
            try:
                # 큐에서 데이터 가져오기 (타임아웃 0.1초)
                data = self._send_queue.get(timeout=0.1)
                self.send_frame(data)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[TelemetryClient] 백그라운드 전송 에러: {e}")

    # =========================================================================
    # Context Manager 지원
    # =========================================================================

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    async def __aenter__(self):
        await self.connect_async()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect_async()


# =============================================================================
# 편의 함수 (Helper Functions)
# =============================================================================

def create_telemetry_client(
    backend_url: str = None,
    robot_id: str = "default_robot"
) -> TelemetryClient:
    """
    텔레메트리 클라이언트를 생성합니다.

    환경변수:
        LEROBOT_BACKEND_URL: 백엔드 서버 URL (기본: ws://localhost:8000)

    Args:
        backend_url: 백엔드 서버 URL (None이면 환경변수 사용)
        robot_id: 로봇 식별자

    Returns:
        TelemetryClient 인스턴스
    """
    return TelemetryClient(backend_url=backend_url, robot_id=robot_id)


# =============================================================================
# 테스트 / 예제
# =============================================================================

if __name__ == "__main__":
    # 간단한 테스트
    print("=" * 50)
    print("TelemetryClient 테스트")
    print("=" * 50)

    client = TelemetryClient(robot_id="test_robot")

    print(f"\n연결 URL: {client.ws_url}")
    print("서버가 실행 중이어야 테스트가 성공합니다.\n")

    # 동기 모드 테스트
    if client.connect():
        for i in range(5):
            success = client.send_frame({
                "observation": {"joint_1": 0.5 + i * 0.1, "joint_2": 1.0},
                "action": {"joint_1": 0.6 + i * 0.1, "joint_2": 1.1}
            })
            print(f"프레임 {i}: {'성공' if success else '실패'}")
            time.sleep(0.1)

        print(f"\n통계: {client.stats.frames_sent} 프레임 전송, {client.stats.fps:.1f} FPS")
        client.disconnect()
    else:
        print("서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.")
        print("uvicorn lerobot.backend.app:app --host 0.0.0.0 --port 8000")
