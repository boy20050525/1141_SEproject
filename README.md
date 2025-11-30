You should add a db.py according to your local database settings.
An example code could be like follows:
--------------------------------------------

from psycopg_pool import AsyncConnectionPool #使用connection pool
from psycopg.rows import dict_row

defaultDB="1141se"
dbUser="postgres"
dbPassword="123456"
dbHost="localhost"
dbPort=5432

DATABASE_URL = f"dbname={defaultDB} user={dbUser} password={dbPassword} host={dbHost} port={dbPort}"
#DATABASE_URL = f"postgresql://{dbUser}:{dbPassword}@{dbHost}:{dbPort}/{defaultDB}"

_pool: AsyncConnectionPool | None = None

async def getDB():
	global _pool
	if _pool is None:
		_pool = AsyncConnectionPool(
			conninfo=DATABASE_URL,
			kwargs={"row_factory": dict_row}, #設定查詢結果以dictionary方式回傳
			open=False #不直接開啟
		)
		await _pool.open() #等待開啟完成

	async with _pool.connection() as conn:

		yield conn
