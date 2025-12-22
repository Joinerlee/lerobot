from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# 기본 설정은 사용하기 쉬운 SQLite입니다. (파일로 저장됨)
# 실제 서비스용(Postgres) 설정 예시: "postgresql+asyncpg://user:password@localhost/dbname"
DATABASE_URL = "sqlite+aiosqlite:///./lerobot_teleop.db"
# DATABASE_URL = "postgresql+asyncpg://user:password@localhost/lerobot"

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    # 비동기 DB 세션 생성기
    async with AsyncSessionLocal() as session:
        yield session
