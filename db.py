from psycopg_pool import AsyncConnectionPool #使用connection pool
from psycopg.rows import dict_row
# db.py
defaultDB="1141se"
dbUser="postgres"
dbPassword="boy20050525"
dbHost="localhost"
dbPort=5432

DATABASE_URL = f"dbname={defaultDB} user={dbUser} password={dbPassword} host={dbHost} port={dbPort}"
#DATABASE_URL = f"postgresql://{dbUser}:{dbPassword}@{dbHost}:{dbPort}/{defaultDB}"

#宣告變數，預設為None
_pool: AsyncConnectionPool | None = None

#取得DB連線物件
async def getDB():
	global _pool
	if _pool is None:
		#lazy create, 等到main.py來呼叫時再啟用 _pool
		_pool = AsyncConnectionPool(
			conninfo=DATABASE_URL,
			kwargs={"row_factory": dict_row}, #設定查詢結果以dictionary方式回傳
			open=False #不直接開啟
		)
		await _pool.open() #等待開啟完成
	#使用with context manager，當結束時自動關閉連線
	async with _pool.connection() as conn:
		#使用yeild generator傳回連線物件
		yield conn
