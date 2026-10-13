"""Redis connection helpers."""

from redis.asyncio import Redis

from app.config import settings


def create_redis_client() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


redis_client = create_redis_client()


async def close_redis_client() -> None:
    await redis_client.aclose()
