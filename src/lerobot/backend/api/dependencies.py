"""
LeRobot Backend API Dependencies

FastAPI dependency injection functions.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal


async def get_db() -> AsyncSession:
    """비동기 DB 세션 생성기 (FastAPI Depends용).

    Yields:
        AsyncSession: SQLAlchemy 비동기 세션

    Example:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        yield session
