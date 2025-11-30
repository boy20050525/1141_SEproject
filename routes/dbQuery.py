from fastapi import APIRouter,Depends
from db import getDB
router = APIRouter()

@router.get("/getUsers")
#使用depends將取得的資料庫連線物件，當成參數注入read_items
async def read_users(conn=Depends(getDB)):
	async with conn.cursor() as cur:
		await cur.execute("SELECT * FROM users;")
		rows = await cur.fetchall()
		return {"items": rows}

@router.get("/findUserByName")
async def read_user(name:str,conn=Depends(getDB)):
	async with conn.cursor() as cur:
		name = f"{name}%"
		sql="SELECT * FROM users where name like %s"
		await cur.execute(sql,(name,))
		rows = await cur.fetchall()
		return {"items": rows}