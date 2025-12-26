
from fastapi import APIRouter, Form, Request, BackgroundTasks, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import psycopg
from psycopg.rows import dict_row
import secrets, datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from db import getDB
import shutil
import time
from dotenv import load_dotenv # 匯入讀取套件

load_dotenv()  # 讀取 .env 檔案

# === Router 模組化設定 ===
router = APIRouter()
templates = Jinja2Templates(directory="templates")

# 讀取變數 (如果讀不到會回傳 None)
SMTP_EMAIL = os.getenv("MAIL_USERNAME")
SMTP_PASSWORD = os.getenv("MAIL_PASSWORD")


# === 登入頁 ===
@router.get("/loginForm", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("loginForm.html", {"request": request})


# === 登入處理 ===
@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    conn=Depends(getDB)
):
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


# === 接收註冊表單 (修正版) ===
@router.post("/register")
async def register_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(...),    # ✅ 新增接收 Email (必填)
    role: str = Form(...),
    phone: str = Form(None),   # ✅ 新增接收 (選填)
    skills: str = Form(None),  # ✅ 新增接收 (選填)
    bio: str = Form(None),     # ✅ 新增接收 (選填)
    avatar_file: UploadFile = File(None), # ✅ 新增接收頭像
    conn=Depends(getDB)
):
    # 1. 處理頭像上傳 (如果有)
    avatar_filename = None
    if avatar_file and avatar_file.filename:
        upload_dir = "www/uploads/avatars"
        os.makedirs(upload_dir, exist_ok=True)
        
        # 產生唯一檔名
        file_ext = avatar_file.filename.split(".")[-1]
        safe_filename = f"user_{int(time.time())}_{secrets.token_hex(4)}.{file_ext}"
        file_path = os.path.join(upload_dir, safe_filename)
        
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(avatar_file.file, buffer)
            avatar_filename = safe_filename
        except Exception as e:
            print(f"❌ 頭像上傳失敗: {e}")

    # 2. 寫入資料庫
    async with conn.cursor() as cur:
        try:
            # 檢查 Email 是否已被註冊
            await cur.execute("SELECT id FROM users WHERE email = %s;", (email,))
            if await cur.fetchone():
                return HTMLResponse("⚠️ Email 已被註冊 <a href='javascript:history.back()'>返回</a>", status_code=400)

            # 寫入所有欄位
            sql = """
                INSERT INTO users 
                (username, password, email, role, phone, skills, bio, avatar, created_at) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
            """
            await cur.execute(
                sql, 
                (username, password, email, role, phone, skills, bio, avatar_filename)
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
async def send_reset_code( # 改名一下比較清楚
    request: Request, 
    background_tasks: BackgroundTasks,
    email: str = Form(...),
    conn=Depends(getDB)
):
    async with conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE email=%s;", (email,))
        user = await cur.fetchone()
        
        if not user:
            # 為了安全，找不到也回傳成功，導向輸入驗證碼頁面 (雖然他收不到)
            return RedirectResponse(url="/verify_code_page", status_code=303)

        # 產生 6 位數驗證碼 (100000 ~ 999999)
        code = str(secrets.randbelow(900000) + 100000)
        expires = datetime.datetime.now() + datetime.timedelta(minutes=10) # 10分鐘有效

        # 寫入 Token 表 (這裡 token 欄位拿來存 6 位數代碼)
        await cur.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s);",
            (user["id"], code, expires)
        )
        await conn.commit()

        # 寄信內容改一下
        send_code_email_task(background_tasks, email, code)

    # 導向到 "輸入驗證碼" 的頁面
    return RedirectResponse(url="/verify_code_page", status_code=303)

# 👇 新增：專門寄驗證碼的函式
def send_code_email_task(background_tasks, to_email, code):
    def _send():
        try:
            msg = MIMEMultipart()
            msg['From'] = SMTP_EMAIL
            msg['To'] = to_email
            msg['Subject'] = "【工作委託平台】密碼重設驗證碼"
            body = f"""
            <html><body>
                <h2>重設密碼驗證</h2>
                <p>您的驗證碼是：<strong style="font-size: 24px; color: #c2a676;">{code}</strong></p>
                <p>驗證碼 10 分鐘內有效，請勿外洩。</p>
            </body></html>
            """
            msg.attach(MIMEText(body, 'html'))
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
            print(f"✅ 驗證碼 {code} 已寄出")
        except Exception as e:
            print(f"❌ 寄信失敗: {e}")
            
    background_tasks.add_task(_send)


# === 顯示重設密碼頁 ===
# === 顯示輸入驗證碼頁面 ===
@router.get("/verify_code_page", response_class=HTMLResponse)
async def verify_code_page(request: Request):
    return templates.TemplateResponse("verify_code.html", {"request": request})

# === 驗證代碼並重設密碼 ===
@router.post("/do_reset_with_code")
async def do_reset_with_code(
    request: Request,
    code: str = Form(...), # 使用者輸入的 6 位數
    password: str = Form(...),
    confirm_password: str = Form(...),
    conn=Depends(getDB)
):
    if password != confirm_password:
        return HTMLResponse("密碼不一致 <a href='javascript:history.back()'>返回</a>", status_code=400)

    async with conn.cursor() as cur:
        # 1. 找看看有沒有這個驗證碼 (且未過期)
        await cur.execute(
            "SELECT user_id FROM password_reset_tokens WHERE token=%s AND expires_at > CURRENT_TIMESTAMP;", 
            (code,)
        )
        record = await cur.fetchone()
        
        if not record:
            return HTMLResponse("❌ 驗證碼錯誤或已過期", status_code=400)

        # 2. 更新密碼
        await cur.execute(
            "UPDATE users SET password=%s WHERE id=%s;",
            (password, record["user_id"])
        )

        # 3. 刪除該驗證碼
        await cur.execute("DELETE FROM password_reset_tokens WHERE token=%s;", (code,))
        await conn.commit()

    return HTMLResponse(
        "<script>alert('✅ 密碼重設成功！');window.location.href='/loginForm';</script>"
    )