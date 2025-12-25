"""
Redis Cache Service for LeRobot Teleoperation.

로봇 상태 캐싱 및 빠른 조회를 위한 Redis 캐시 서비스.
Redis 미설정 시 인메모리 캐시로 폴백합니다.

Usage:
    from services.cache import cache_service

    # 로봇 상태 업데이트
    await cache_service.update_robot_status("robot_1", {"position": [0, 0, 0]})

    # 온라인 로봇 목록 조회
    robots = await cache_service.get_online_robots()

    # 특정 로봇 상태 조회
    status = await cache_service.get_robot_status("robot_1")
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from lerobot.backend.core.config import settings
from lerobot.backend.core.logging import get_logger

logger = get_logger(__name__)

# Redis 패키지 체크
try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis 패키지 미설치, 인메모리 캐시로 폴백")


@dataclass
class RobotStatus:
    """로봇 상태 데이터."""

    robot_id: str
    status: dict[str, Any]
    last_seen: float
    session_id: int | None = None


@dataclass
class CacheStats:
    """캐시 통계."""

    hits: int = 0
    misses: int = 0
    updates: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        """캐시 히트율."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class InMemoryCache:
    """Redis 폴백용 인메모리 캐시."""

    def __init__(self, default_ttl: float = 30.0):
        self._cache: dict[str, tuple[Any, float]] = {}  # key -> (value, expire_time)
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        """키로 값 조회."""
        async with self._lock:
            if key in self._cache:
                value, expire_time = self._cache[key]
                if time.time() < expire_time:
                    return value
                # 만료됨
                del self._cache[key]
            return None

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """값 저장."""
        ttl = ttl or self._default_ttl
        expire_time = time.time() + ttl
        async with self._lock:
            self._cache[key] = (value, expire_time)

    async def delete(self, key: str) -> bool:
        """키 삭제."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def keys(self, pattern: str) -> list[str]:
        """패턴에 맞는 키 목록 (간단한 prefix 매칭)."""
        prefix = pattern.rstrip("*")
        now = time.time()
        async with self._lock:
            # 만료된 키 정리
            expired = [k for k, (_, exp) in self._cache.items() if exp <= now]
            for k in expired:
                del self._cache[k]
            # 패턴 매칭
            return [k for k in self._cache.keys() if k.startswith(prefix)]

    async def mget(self, keys: list[str]) -> list[Any | None]:
        """여러 키 조회."""
        return [await self.get(k) for k in keys]

    async def ping(self) -> bool:
        """연결 확인."""
        return True

    async def close(self) -> None:
        """리소스 정리."""
        async with self._lock:
            self._cache.clear()


class RobotCache:
    """로봇 상태 캐싱 서비스.

    Features:
        - 로봇 상태 업데이트 (30초 TTL)
        - 온라인 로봇 목록 조회 (< 1ms)
        - Redis 연결 풀 사용
        - Redis 미설정 시 인메모리 캐시로 폴백
    """

    # Redis 키 접두사
    ROBOT_STATUS_PREFIX = "robot:status:"
    ROBOT_SESSION_PREFIX = "robot:session:"
    ONLINE_ROBOTS_KEY = "robots:online"

    def __init__(
        self,
        redis_url: str | None = None,
        default_ttl: float = 30.0,
        pool_size: int = 10,
    ):
        """초기화.

        Args:
            redis_url: Redis 연결 URL
            default_ttl: 기본 TTL (초)
            pool_size: 연결 풀 크기
        """
        self._redis_url = redis_url or settings.REDIS_URL
        self._default_ttl = default_ttl
        self._pool_size = pool_size
        self._redis: aioredis.Redis | None = None
        self._memory_cache: InMemoryCache | None = None
        self._stats = CacheStats()
        self._initialized = False
        self._use_redis = False

    async def initialize(self) -> None:
        """캐시 초기화."""
        if self._initialized:
            return

        if REDIS_AVAILABLE and self._redis_url:
            try:
                self._redis = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=self._pool_size,
                )
                # 연결 테스트
                await self._redis.ping()
                self._use_redis = True
                logger.info(
                    "Redis 캐시 초기화 완료",
                    url=self._redis_url.split("@")[-1],  # 비밀번호 숨김
                    pool_size=self._pool_size,
                )
            except Exception as e:
                logger.warning("Redis 연결 실패, 인메모리 캐시로 폴백", error=str(e))
                self._redis = None
                self._use_redis = False

        if not self._use_redis:
            self._memory_cache = InMemoryCache(default_ttl=self._default_ttl)
            logger.info("인메모리 캐시 초기화 완료", ttl=self._default_ttl)

        self._initialized = True

    async def _ensure_initialized(self) -> None:
        """초기화 확인."""
        if not self._initialized:
            await self.initialize()

    @property
    def _cache(self) -> aioredis.Redis | InMemoryCache:
        """현재 사용 중인 캐시."""
        if self._use_redis and self._redis:
            return self._redis
        return self._memory_cache

    async def update_robot_status(
        self,
        robot_id: str,
        status: dict[str, Any],
        session_id: int | None = None,
        ttl: float | None = None,
    ) -> None:
        """로봇 상태 업데이트.

        Args:
            robot_id: 로봇 ID
            status: 상태 데이터
            session_id: 세션 ID (선택)
            ttl: TTL (초, 기본 30초)
        """
        await self._ensure_initialized()
        ttl = ttl or self._default_ttl

        # 상태 데이터 구성
        robot_status = RobotStatus(
            robot_id=robot_id,
            status=status,
            last_seen=time.time(),
            session_id=session_id,
        )
        status_key = f"{self.ROBOT_STATUS_PREFIX}{robot_id}"
        status_data = json.dumps({
            "robot_id": robot_status.robot_id,
            "status": robot_status.status,
            "last_seen": robot_status.last_seen,
            "session_id": robot_status.session_id,
        })

        if self._use_redis and self._redis:
            # Redis 사용
            pipe = self._redis.pipeline()
            pipe.set(status_key, status_data, ex=int(ttl))
            pipe.sadd(self.ONLINE_ROBOTS_KEY, robot_id)
            pipe.expire(self.ONLINE_ROBOTS_KEY, int(ttl * 2))  # 온라인 목록은 더 긴 TTL
            await pipe.execute()
        else:
            # 인메모리 캐시
            await self._memory_cache.set(status_key, status_data, ttl)
            # 온라인 로봇 목록 업데이트
            online_set = await self._memory_cache.get(self.ONLINE_ROBOTS_KEY) or set()
            if isinstance(online_set, str):
                online_set = set(json.loads(online_set))
            online_set.add(robot_id)
            await self._memory_cache.set(
                self.ONLINE_ROBOTS_KEY,
                json.dumps(list(online_set)),
                ttl * 2,
            )

        self._stats.updates += 1
        logger.debug(
            "로봇 상태 업데이트",
            robot_id=robot_id,
            session_id=session_id,
            ttl=ttl,
        )

    async def get_robot_status(self, robot_id: str) -> RobotStatus | None:
        """로봇 상태 조회.

        Args:
            robot_id: 로봇 ID

        Returns:
            RobotStatus 또는 None
        """
        await self._ensure_initialized()
        status_key = f"{self.ROBOT_STATUS_PREFIX}{robot_id}"

        if self._use_redis and self._redis:
            data = await self._redis.get(status_key)
        else:
            data = await self._memory_cache.get(status_key)

        if data:
            self._stats.hits += 1
            parsed = json.loads(data)
            return RobotStatus(
                robot_id=parsed["robot_id"],
                status=parsed["status"],
                last_seen=parsed["last_seen"],
                session_id=parsed.get("session_id"),
            )

        self._stats.misses += 1
        return None

    async def get_online_robots(self) -> list[str]:
        """온라인 로봇 목록 조회.

        Returns:
            온라인 로봇 ID 목록
        """
        await self._ensure_initialized()

        if self._use_redis and self._redis:
            # Redis SMEMBERS는 O(N)이지만 매우 빠름
            members = await self._redis.smembers(self.ONLINE_ROBOTS_KEY)
            return list(members) if members else []
        else:
            # 인메모리 캐시
            data = await self._memory_cache.get(self.ONLINE_ROBOTS_KEY)
            if data:
                return json.loads(data) if isinstance(data, str) else list(data)
            return []

    async def get_online_robot_statuses(self) -> list[RobotStatus]:
        """모든 온라인 로봇의 상태 조회.

        Returns:
            RobotStatus 목록
        """
        await self._ensure_initialized()
        robot_ids = await self.get_online_robots()

        if not robot_ids:
            return []

        keys = [f"{self.ROBOT_STATUS_PREFIX}{rid}" for rid in robot_ids]

        if self._use_redis and self._redis:
            values = await self._redis.mget(keys)
        else:
            values = await self._memory_cache.mget(keys)

        statuses = []
        for data in values:
            if data:
                parsed = json.loads(data)
                statuses.append(RobotStatus(
                    robot_id=parsed["robot_id"],
                    status=parsed["status"],
                    last_seen=parsed["last_seen"],
                    session_id=parsed.get("session_id"),
                ))

        return statuses

    async def remove_robot(self, robot_id: str) -> bool:
        """로봇 상태 제거.

        Args:
            robot_id: 로봇 ID

        Returns:
            성공 여부
        """
        await self._ensure_initialized()
        status_key = f"{self.ROBOT_STATUS_PREFIX}{robot_id}"

        if self._use_redis and self._redis:
            pipe = self._redis.pipeline()
            pipe.delete(status_key)
            pipe.srem(self.ONLINE_ROBOTS_KEY, robot_id)
            results = await pipe.execute()
            removed = results[0] > 0
        else:
            removed = await self._memory_cache.delete(status_key)
            # 온라인 목록에서 제거
            data = await self._memory_cache.get(self.ONLINE_ROBOTS_KEY)
            if data:
                online_set = set(json.loads(data) if isinstance(data, str) else data)
                online_set.discard(robot_id)
                await self._memory_cache.set(
                    self.ONLINE_ROBOTS_KEY,
                    json.dumps(list(online_set)),
                    self._default_ttl * 2,
                )

        if removed:
            self._stats.evictions += 1
            logger.debug("로봇 상태 제거", robot_id=robot_id)

        return removed

    async def invalidate_session(self, session_id: int) -> int:
        """세션의 모든 로봇 상태 무효화.

        Args:
            session_id: 세션 ID

        Returns:
            무효화된 로봇 수
        """
        await self._ensure_initialized()
        statuses = await self.get_online_robot_statuses()
        count = 0

        for status in statuses:
            if status.session_id == session_id:
                await self.remove_robot(status.robot_id)
                count += 1

        if count > 0:
            logger.info("세션 캐시 무효화", session_id=session_id, count=count)

        return count

    async def health_check(self) -> dict[str, Any]:
        """캐시 상태 확인.

        Returns:
            상태 정보
        """
        await self._ensure_initialized()

        result = {
            "type": "redis" if self._use_redis else "memory",
            "healthy": False,
            "stats": {
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "updates": self._stats.updates,
                "evictions": self._stats.evictions,
                "hit_rate": f"{self._stats.hit_rate:.2%}",
            },
        }

        try:
            if self._use_redis and self._redis:
                await self._redis.ping()
                info = await self._redis.info("memory")
                result["healthy"] = True
                result["memory_used"] = info.get("used_memory_human", "unknown")
            else:
                await self._memory_cache.ping()
                result["healthy"] = True
        except Exception as e:
            result["error"] = str(e)

        return result

    async def close(self) -> None:
        """리소스 정리."""
        if self._redis:
            await self._redis.close()
            self._redis = None
        if self._memory_cache:
            await self._memory_cache.close()
            self._memory_cache = None
        self._initialized = False
        logger.info("캐시 서비스 종료")


# 싱글톤 인스턴스
cache_service = RobotCache()
