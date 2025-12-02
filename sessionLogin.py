from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import psycopg
from psycopg.rows import dict_row
import secrets, datetime

# === Router 模組化設定 ===
router = APIRouter()
templates = Jinja2Templates(directory="templates")

# === 資料庫連線 ===
async def getDB():
    conn = await psycopg.AsyncConnection.connect(
        "dbname=114se3 user=postgres password=123456 host=localhost port=5432",
        row_factory=dict_row
    )
    return conn


# === 登入頁 ===
@router.get("/loginForm", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("loginForm.html", {"request": request})


# === 登入處理 ===
@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    conn = await getDB()
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT * FROM users WHERE username=%s AND password=%s;",
            (username, password)
        )
        user = await cur.fetchone()

    if not user:
        return HTMLResponse("❌ 帳號或密碼錯誤 <a href='/loginForm'>返回登入</a>", status_code=401)

    # 建立登入 session
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]

    return RedirectResponse(url="/", status_code=302)


# === 登出 ===
@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/loginForm")


# === 註冊頁 ===
@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


# === 接收註冊表單 ===
@router.post("/register")
async def register_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    conn = await getDB()
    async with conn.cursor() as cur:
        try:
            await cur.execute(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, %s);",
                (username, password, role)
            )
            await conn.commit()
        except Exception as e:
            return HTMLResponse(f"⚠️ 註冊失敗：{e}<br><a href='/register'>返回重試</a>", status_code=400)

    return HTMLResponse("✅ 註冊成功！<a href='/loginForm'>返回登入</a>", status_code=200)


# === 忘記密碼頁 ===
@router.get("/forgot", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("forgot.html", {"request": request})


# === 寄出重設密碼信 ===
@router.post("/forgot")
async def send_reset_email(request: Request, email: str = Form(...)):
    conn = await getDB()
    async with conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE email=%s;", (email,))
        user = await cur.fetchone()
        if not user:
            return HTMLResponse("❌ 找不到該 Email。<a href='/forgot'>返回</a>", status_code=404)

        # 產生 Token
        token = secrets.token_urlsafe(32)
        expires = datetime.datetime.now() + datetime.timedelta(hours=1)

        # 寫入 Token 表
        await cur.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s);",
            (user["id"], token, expires)
        )
        await conn.commit()

    # （此處可整合 SMTP 寄信邏輯）
    reset_link = f"http://localhost:8000/reset?token={token}"
    print(f"🔗 重設連結（測試用）: {reset_link}")

    return HTMLResponse(f"✅ 已寄出重設連結至 {email}（<a href='{reset_link}'>立即重設</a>）", status_code=200)


# === 顯示重設密碼頁 ===
@router.get("/reset", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str):
    return templates.TemplateResponse("reset.html", {"request": request, "token": token})


# === 接收新密碼提交 ===
@router.post("/reset")
async def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
):
    conn = await getDB()
    async with conn.cursor() as cur:
        # 驗證 token
        await cur.execute(
            "SELECT user_id, expires_at FROM password_reset_tokens WHERE token=%s;", (token,)
        )
        record = await cur.fetchone()
        if not record:
            return HTMLResponse("❌ 無效的重設連結", status_code=400)

        # 檢查是否過期
        if record["expires_at"] < datetime.datetime.now():
            return HTMLResponse("⚠️ 連結已過期", status_code=400)

        # 更新密碼
        await cur.execute(
            "UPDATE users SET password=%s WHERE id=%s;",
            (password, record["user_id"])
        )

        # 移除 token
        await cur.execute("DELETE FROM password_reset_tokens WHERE token=%s;", (token,))
        await conn.commit()

    return HTMLResponse("✅ 密碼重設成功！<a href='/loginForm'>返回登入</a>", status_code=200)
