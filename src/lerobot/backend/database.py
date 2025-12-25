"""
LeRobot Backend Database Configuration

SQLAlchemy async engine 설정.
환경변수를 통해 SQLite/PostgreSQL 전환 가능.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from .core.config import settings

# 환경변수 기반 엔진 생성
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# get_db는 api/dependencies.py로 이동됨
