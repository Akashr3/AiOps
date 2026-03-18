import asyncio
import logging
import os

import asyncpg

logger = logging.getLogger(__name__)


class Database:
    pool: asyncpg.Pool | None = None

    @classmethod
    async def connect(cls, service_name: str, max_retries: int = 10) -> None:
        for attempt in range(1, max_retries + 1):
            try:
                cls.pool = await asyncpg.create_pool(
                    host=os.getenv("DB_HOST", "postgres"),
                    port=int(os.getenv("DB_PORT", "5432")),
                    user=os.getenv("DB_USER", "aegis"),
                    password=os.getenv("DB_PASSWORD", "aegis_demo_password"),
                    database=os.getenv("DB_NAME", "aegis"),
                    min_size=int(os.getenv("DB_POOL_MIN", "2")),
                    max_size=int(os.getenv("DB_POOL_MAX", "10")),
                )
                logger.info(
                    "Database connected",
                    extra={"service": service_name, "attempt": attempt},
                )
                return
            except (asyncpg.PostgresError, OSError) as exc:
                wait = min(2 ** attempt, 30)
                logger.warning(
                    f"DB connection attempt {attempt}/{max_retries} failed, retrying in {wait}s",
                    extra={"service": service_name, "error": str(exc)},
                )
                await asyncio.sleep(wait)
        raise RuntimeError("Could not connect to the database")

    @classmethod
    async def disconnect(cls) -> None:
        if cls.pool:
            await cls.pool.close()
            logger.info("Database disconnected")

    @classmethod
    async def fetch_one(cls, query: str, *args):
        async with cls.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    @classmethod
    async def fetch_all(cls, query: str, *args):
        async with cls.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    @classmethod
    async def execute(cls, query: str, *args):
        async with cls.pool.acquire() as conn:
            return await conn.execute(query, *args)
