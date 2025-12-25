"""
LeRobot Backend Configuration

pydantic-settings 기반 환경변수 관리.
모든 설정은 .env 파일 또는 환경변수로 오버라이드 가능.
"""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ==========================================================================
    # Application
    # ==========================================================================
    APP_NAME: str = "LeRobot Backend"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # ==========================================================================
    # Database
    # ==========================================================================
    # SQLite (기본): sqlite+aiosqlite:///./lerobot_teleop.db
    # PostgreSQL: postgresql+asyncpg://user:password@localhost:5432/lerobot
    DATABASE_URL: str = "sqlite+aiosqlite:///./lerobot_teleop.db"
    DB_ECHO: bool = False  # SQL 쿼리 로깅

    # ==========================================================================
    # Redis (Optional - for caching)
    # ==========================================================================
    REDIS_URL: Optional[str] = None  # redis://localhost:6379/0

    # ==========================================================================
    # AWS S3 (for video storage)
    # ==========================================================================
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "ap-northeast-2"
    S3_BUCKET_NAME: str = "lerobot-teleoperation-data"
    S3_ENDPOINT_URL: Optional[str] = None  # MinIO, LocalStack 등 커스텀 엔드포인트
    S3_MULTIPART_THRESHOLD: int = 8 * 1024 * 1024  # 8MB 이상 시 멀티파트
    S3_MULTIPART_CHUNK_SIZE: int = 8 * 1024 * 1024  # 멀티파트 청크 크기

    # 허용 비디오 확장자 및 최대 크기
    VIDEO_ALLOWED_EXTENSIONS: list[str] = ["mp4", "avi", "mov", "webm"]
    VIDEO_MAX_SIZE_MB: int = 500  # 최대 500MB

    # ==========================================================================
    # File Storage
    # ==========================================================================
    BACKUP_DIR: Path = Path("./lerobot_backup")

    # ==========================================================================
    # WebSocket & Performance
    # ==========================================================================
    WS_BUFFER_SIZE: int = 60  # 프레임 버퍼 크기 (60fps = 1초)
    WS_HEARTBEAT_INTERVAL: int = 30  # 초

    # ==========================================================================
    # Security (Task 2.3 준비)
    # ==========================================================================
    API_KEY: Optional[str] = None  # API 인증 키 (설정 시 인증 활성화)

    # ==========================================================================
    # Logging
    # ==========================================================================
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_FORMAT: str = "json"  # json 또는 text

    @property
    def is_sqlite(self) -> bool:
        """SQLite 사용 여부 확인."""
        return "sqlite" in self.DATABASE_URL.lower()

    @property
    def is_postgres(self) -> bool:
        """PostgreSQL 사용 여부 확인."""
        return "postgresql" in self.DATABASE_URL.lower()

    @property
    def backup_path(self) -> Path:
        """백업 디렉토리 Path 객체 반환."""
        return Path(self.BACKUP_DIR)


# 싱글톤 인스턴스
settings = Settings()
