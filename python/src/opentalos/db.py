"""跨模块共享的数据库连接辅助函数。"""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    # asyncpg 驱动需要 "postgresql+asyncpg://" 前缀，而不是纯 "postgresql://"。
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return create_async_engine(database_url, pool_pre_ping=True)
