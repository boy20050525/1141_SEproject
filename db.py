from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

defaultDB = "114se3"
dbUser = "postgres"
dbPassword = "123456"
dbHost = "localhost"
dbPort = 5432

DATABASE_URL = f"dbname={defaultDB} user={dbUser} password={dbPassword} host={dbHost} port={dbPort}"

_pool: AsyncConnectionPool | None = None

async def getDB():
    global _pool
    if _pool is None:
        # 第一次呼叫時建立連線池
        _pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=5,
            open=False  # lazy open
        )
        await _pool.open()
        await _pool.wait()  # 確保連線池已可用

    async with _pool.connection() as conn:
        conn.row_factory = dict_row  # 查詢結果以 dict 形式回傳
        yield conn
