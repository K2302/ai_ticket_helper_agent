import asyncpg


class Database:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=10)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    def require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("Database pool is not initialized")
        return self.pool
