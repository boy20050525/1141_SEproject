# db.py
import os
from dotenv import load_dotenv
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

# 1. 載入 .env 檔案
load_dotenv()

# 2. 組合連線字串 (使用 .env 裡的變數)
DATABASE_URL = f"dbname={os.getenv('DB_NAME')} user={os.getenv('DB_USER')} password={os.getenv('DB_PASSWORD')} host={os.getenv('DB_HOST')} port={os.getenv('DB_PORT')}"

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