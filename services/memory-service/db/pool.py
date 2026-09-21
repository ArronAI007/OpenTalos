from psycopg_pool import AsyncConnectionPool


def create_pool(database_url: str) -> AsyncConnectionPool:
    """跟 TS 那边所有 postgres-memory 函数一样，pool 由调用方（app 启动逻辑、或测试）显式构造并
    传入每个函数——不用模块级单例，保持每个函数可以直接用任意 pool（生产 pool、或测试用
    testcontainer pool）调用，不依赖全局状态。"""
    return AsyncConnectionPool(database_url, open=False)
