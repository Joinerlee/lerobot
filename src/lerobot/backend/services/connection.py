"""
LeRobot Backend Connection Manager

WebSocket connection management for teleoperation.
향후 Redis pub/sub 확장을 위한 서비스 레이어.
"""

from fastapi import WebSocket


class ConnectionManager:
    """WebSocket 연결을 관리하는 매니저 클래스.

    Attributes:
        active_connections: 현재 활성화된 WebSocket 연결 목록

    향후 확장 계획:
        - Redis pub/sub 기반 다중 서버 연결 공유
        - 연결별 메타데이터 관리 (robot_id, session_id)
        - 연결 상태 모니터링
    """

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """새 WebSocket 연결을 수락하고 목록에 추가.

        Args:
            websocket: 연결할 WebSocket 인스턴스
        """
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """WebSocket 연결을 목록에서 제거.

        Args:
            websocket: 제거할 WebSocket 인스턴스
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str) -> None:
        """모든 연결된 클라이언트에게 메시지 전송.

        Args:
            message: 전송할 메시지
        """
        for connection in self.active_connections:
            await connection.send_text(message)

    @property
    def connection_count(self) -> int:
        """현재 활성 연결 수 반환."""
        return len(self.active_connections)


# 싱글톤 인스턴스
manager = ConnectionManager()
