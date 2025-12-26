# main.py

from fastapi import FastAPI, Depends, Request, Form, HTTPException

from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse

from fastapi.staticfiles import StaticFiles

from fastapi.templating import Jinja2Templates

from starlette.middleware.sessions import SessionMiddleware

from sessionLogin import router as login_router

from fastapi import File, UploadFile, BackgroundTasks

from datetime import datetime

import smtplib

from email.mime.text import MIMEText

from email.mime.multipart import MIMEMultipart

import os

import time

import shutil


from db import getDB

import jobs  # 對應 jobs.py（原本的 posts.py 改名後）

from fastapi import WebSocket, WebSocketDisconnect
from typing import List, Dict
import json

# 載入 routes 子模組

from routes.upload import router as upload_router

from routes.dbQuery import router as db_router

from datetime import datetime, timedelta
from routes.ratings import router as rating_router
from routes import ratings as ratings_module
from fastapi.responses import JSONResponse
# =============================

# 初始化 FastAPI 應用

# =============================

app = FastAPI(title="工作委託平台")



# Session Middleware（用於登入狀態保存）

app.add_middleware(

    SessionMiddleware,

    secret_key="your-secret-key",   # ⚠️ 請自行更改為安全的隨機字串

    same_site="lax",

    https_only=False

)



# Jinja2 模板設定

templates = Jinja2Templates(directory="templates")



# 掛載路由模組

app.include_router(upload_router, prefix="/api")

app.include_router(db_router, prefix="/api")

app.include_router(login_router)
app.include_router(rating_router, prefix="/api")


# === WebSocket Connection Manager (修改版) ===
class ConnectionManager:
    def __init__(self):
        # 原本的聊天室連線: {job_id: [websocket, ...]}
        self.active_connections: Dict[int, List[WebSocket]] = {}
        
        # 🔥 新增：全域通知連線: {user_id: websocket}
        # 假設每個使用者同一時間只有一個主要的通知連線 (若有多分頁需求可改為 List)
        self.user_connections: Dict[int, WebSocket] = {}

    # --- 1. 聊天室相關 (保持不變，或稍微調整) ---
    async def connect(self, websocket: WebSocket, job_id: int):
        await websocket.accept()
        if job_id not in self.active_connections:
            self.active_connections[job_id] = []
        self.active_connections[job_id].append(websocket)

    def disconnect(self, websocket: WebSocket, job_id: int):
        if job_id in self.active_connections:
            if websocket in self.active_connections[job_id]:
                self.active_connections[job_id].remove(websocket)

    async def broadcast(self, message: dict, job_id: int):
        if job_id in self.active_connections:
            json_msg = json.dumps(message, default=str)
            for connection in self.active_connections[job_id]:
                try:
                    await connection.send_text(json_msg)
                except:
                    pass

    # --- 2. 🔥 新增：全域通知相關 ---
    async def connect_user(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        # 儲存使用者的連線
        self.user_connections[user_id] = websocket

    def disconnect_user(self, user_id: int):
        if user_id in self.user_connections:
            del self.user_connections[user_id]

    # 發送給「特定」使用者 (例如：有人報價，通知該案件的甲方)
    async def send_to_user(self, user_id: int, message: dict):
        if user_id in self.user_connections:
            try:
                await self.user_connections[user_id].send_text(json.dumps(message, default=str))
            except:
                pass

    # 發送給「所有」特定角色的使用者 (例如：新工作通知所有乙方)
    # 這邊我們簡單做：直接廣播給所有連線中的人，前端自己判斷要不要顯示
    async def broadcast_global(self, message: dict):
        json_msg = json.dumps(message, default=str)
        for user_id, connection in self.user_connections.items():
            try:
                await connection.send_text(json_msg)
            except:
                pass

manager = ConnectionManager()

# === 全域通知 WebSocket ===
@app.websocket("/ws/notify/{user_id}")
async def notify_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect_user(websocket, user_id)
    try:
        while True:
            # 保持連線，只需接收 keepalive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_user(user_id)


# =============================

# 靜態檔案掛載

# =============================

app.mount("/static", StaticFiles(directory="www"), name="static")


# =============================

# 首頁（工作清單）

# =============================

@app.get("/")

async def home(request: Request, conn=Depends(getDB)):

    user_id = request.session.get("user_id")

    role = request.session.get("role")

    username = None



    # 若有登入，查出對應的使用者名稱

    if user_id:

        async with conn.cursor() as cur:

            await cur.execute("SELECT username FROM users WHERE id = %s;", (user_id,))

            result = await cur.fetchone()

            if result:

                username = result["username"]



    # === 新增這行：讀取網址列的 ?status= 參數 ===

    selected_status = request.query_params.get("status")



    # === 根據選擇狀態查詢 ===

    if selected_status and selected_status != "":

        job_list = await jobs.getJobsByStatus(conn, selected_status, current_user_id=user_id)

    else:

        job_list = await jobs.getJobList(conn, current_user_id=user_id)



    return templates.TemplateResponse(

        "jobList.html",

        {

            "request": request,

            "items": job_list,

            "user_id": user_id,

            "role": role,

            "username": username,

            "current_status": selected_status or ""  # 給前端記住選項

        }

    )

# 在 main.py 的「甲方 / 乙方 Dashboard」區塊附近加入

@app.get("/editProfile")
async def edit_profile_form(request: Request, conn=Depends(getDB)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/loginForm", status_code=302)

    # 1. 查詢使用者基本資料
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM users WHERE id = %s;", (user_id,))
        user = await cur.fetchone()

    if not user:
        return HTMLResponse("找不到使用者", status_code=404)


    blocked_list = await jobs.getBlockedUsers(conn, user_id)

    return templates.TemplateResponse("editProfile.html", {
        "request": request,
        "user": user,
        "blocked_users": blocked_list  # 👈 這就是關鍵！把資料傳給 HTML
    })

@app.post("/editProfile")
async def edit_profile_submit(
    request: Request,
    username: str = Form(...),
    phone: str = Form(None),
    skills: str = Form(None),
    bio: str = Form(None),
    avatar_file: UploadFile = File(None),
    conn=Depends(getDB)
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/loginForm", status_code=302)

    # 處理頭像上傳 (邏輯同註冊)
    avatar_sql = ""
    params = [username, phone, skills, bio]

    if avatar_file and avatar_file.filename:
        upload_dir = "www/uploads/avatars"
        os.makedirs(upload_dir, exist_ok=True)
        file_ext = avatar_file.filename.split(".")[-1]
        safe_filename = f"user_{user_id}_{int(time.time())}.{file_ext}"
        file_path = os.path.join(upload_dir, safe_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(avatar_file.file, buffer)
        
        avatar_sql = ", avatar = %s"
        params.append(safe_filename)

    params.append(user_id) # 最後一個 %s 是 WHERE id = %s

    async with conn.cursor() as cur:
        sql = f"UPDATE users SET username=%s, phone=%s, skills=%s, bio=%s {avatar_sql} WHERE id=%s"
        await cur.execute(sql, tuple(params))
        await conn.commit()

    # 更新 Session 中的名稱（避免 Header 顯示舊名字）
    request.session["username"] = username

    return HTMLResponse("<script>alert('更新成功！'); window.location.href='/';</script>")


# === 顯示案件詳情 (含競標清單 + 上傳檔案資訊) ===

@app.get("/read/{id}")

async def readJob(request: Request, id: int, conn=Depends(getDB)):

    # 從 jobs.py 抓取案件資訊

    jobDetail = await jobs.getJob(conn, id)



    # 競標清單（乙方報價）

    bids = await jobs.getBids(conn, id)



    # === 修改開始 ===

    # 上傳成果（乙方已交付的檔案資訊）

    # 修改：使用 getDeliverables (複數) 抓取該案件的所有歷史版本
    deliverables = await jobs.getDeliverables(conn, id)
    # 在 main.py 中呼叫評價相關函式
    rating_deadline = None
    job_ratings = None

    # 只在案件已完成時查詢評價信息
    if jobDetail and jobDetail["status"] == "已完成":
        rating_deadline = await ratings_module.getRatingDeadline(conn, id)
        job_ratings = await ratings_module.getJobRatings(conn, id)
     # === 新增：取得該案件的 Issue 列表 ===

    issue_list = await jobs.getIssues(conn, id)



    # 為了相容前端原本使用 "deliverable" 來判斷是否有退件原因

    # 我們取列表中的最後一筆（最新版）當作目前的狀態

    latest_deliverable = deliverables[-1] if deliverables else None

    # === 修改結束 ===



    # ⚠️ 截止日期檢查

    is_expired = False

    if jobDetail and jobDetail.get("deadline"):

        # 簡單的時間比較邏輯

        is_expired = datetime.now() > jobDetail["deadline"]

        # 傳到模板 jobDetail.html

    return templates.TemplateResponse(

        "jobDetail.html",

        {

            "request": request,

            "job": jobDetail,

            "bids": bids,

            "is_expired": is_expired,
            "deliverables": deliverables,      # 🆕 新增：傳入完整歷史清單給前端表格使用
            "rating_deadline": rating_deadline, 
            "deliverable": latest_deliverable,  # 🔄 保留：傳入最新一筆 (維持舊有邏輯相容性，例如退件紅字顯示)
            "job_ratings": job_ratings,
            "issues": issue_list  # 傳遞到前端

        }

    )

# =============================

# 新增工作（甲方）

# =============================

@app.get("/addJobForm")

async def add_job_form(request: Request):

    # 僅限甲方

    if request.session.get("role") != "甲方":

        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse("addJobForm.html", {"request": request})



@app.post("/addJob")

async def add_job(

    request: Request,

    title: str = Form(...),

    content: str = Form(...),

    budget: int = Form(...),

    deadline: str = Form(...), # 👈 新增 deadline 接收

    requirement_file: UploadFile = File(None),   # 👈 新增上傳檔案

    conn=Depends(getDB)

):

    user_id = request.session.get("user_id")

    role = request.session.get("role")



    if not user_id or role != "甲方":

        raise HTTPException(status_code=403, detail="只有甲方可新增工作")

    # ✅ 新增驗證邏輯：精確到分鐘的比較
    try:
        # 將前端傳來的字串轉為 datetime 物件
        # datetime-local 傳來的格式固定為 "%Y-%m-%dT%H:%M"
        deadline_dt = datetime.strptime(deadline, "%Y-%m-%dT%H:%M")
        
        # 取得現在時間 (無秒數差異比較)
        now = datetime.now()
        
        if deadline_dt <= now:
            return HTMLResponse(
                f"""
                <script>
                    alert('❌ 設定失敗！截止時間不能早於現在時間 ({now.strftime("%Y-%m-%d %H:%M")})');
                    history.back();
                </script>
                """, 
                status_code=400
            )
    except ValueError:
        return HTMLResponse("❌ 時間格式錯誤", status_code=400)

    file_path = None

    # ⚠️ 修改：檢查檔案是否存在且名稱不為空

    if requirement_file and requirement_file.filename:

        upload_dir = "uploads/requirements"

        

        # 1. 確保資料夾存在

        os.makedirs(upload_dir, exist_ok=True)

        

        # 2. 確保安全檔名：使用時間戳 + 原始檔名

        # 移除檔名中可能導致路徑問題的字元 (例如: / 或 \)

        safe_filename = requirement_file.filename.split('/')[-1].split('\\')[-1]

        

        # 加上時間戳，確保唯一性

        safe_filename = f"{int(time.time())}_{safe_filename}"

        

        # 3. 組合檔案路徑

        file_path = os.path.join(upload_dir, safe_filename)



        # 4. 寫入檔案

        try:

            with open(file_path, "wb") as f:

                # 寫入檔案內容

                f.write(await requirement_file.read())

        except Exception as e:

            # 如果寫入失敗，回傳詳細錯誤訊息

            raise HTTPException(status_code=500, detail=f"檔案寫入失敗: {e}")

        

    await jobs.addJob(conn, title, content, budget, user_id, file_path, deadline)

    # 🔥🔥 新增：廣播新工作通知 🔥🔥
    notification = {
        "type": "new_job",
        "title": title,
        "budget": budget,
        "client": request.session.get("username"),
        "message": f"🔥 新工作快報：{title} (預算 ${budget})"
    }
    # 這裡我們廣播給所有人，前端會自己過濾是否為乙方
    await manager.broadcast_global(notification)

    return RedirectResponse(url="/dashboard_client", status_code=302)


# =============================

# 刪除工作（甲方）

# =============================

@app.get("/delete/{id}")

async def delete_job(request: Request, id: int, conn=Depends(getDB)):

    user_id = request.session.get("user_id")

    role = request.session.get("role")



    if not user_id or role != "甲方":

        raise HTTPException(status_code=403, detail="只有甲方可刪除工作")



    await jobs.deleteJob(conn, id, user_id)

    return RedirectResponse(url="/", status_code=302)




# =============================

# 甲方 / 乙方 Dashboard

# =============================

@app.get("/dashboard_client")

async def dashboard_client(request: Request, conn=Depends(getDB)):

    if request.session.get("role") != "甲方":

        return RedirectResponse(url="/", status_code=302)



    client_id = request.session.get("user_id")

    my_jobs = await jobs.getJobsByClient(conn, client_id)

    return templates.TemplateResponse(

        "dashboard_client.html",

        {"request": request, "jobs": my_jobs}

    )



@app.get("/dashboard_freelancer")

async def dashboard_freelancer(request: Request, conn=Depends(getDB)):

    if request.session.get("role") != "乙方":

        return RedirectResponse(url="/", status_code=302)



    freelancer_id = request.session.get("user_id")

    available_jobs = await jobs.getAvailableJobs(conn, current_user_id=freelancer_id)
    my_jobs = await jobs.getJobsByFreelancer(conn, freelancer_id)



    return templates.TemplateResponse(

        "dashboard_freelancer.html",

        {

            "request": request,

            "available_jobs": available_jobs,

            "my_jobs": my_jobs

        }

    )

# --- 乙方提出接案申請 ---

@app.post("/requestJob")

async def request_job(

    request: Request,

    job_id: int = Form(...),

    conn=Depends(getDB)

):

    freelancer_id = request.session.get("user_id")

    role = request.session.get("role")



    if role != "乙方":

        return RedirectResponse(url="/", status_code=302)



    await jobs.requestJob(conn, job_id, freelancer_id)

    return RedirectResponse(url=f"/read/{job_id}", status_code=302)





# --- 甲方確認接案 ---

@app.post("/confirmJob")

async def confirm_job(

    request: Request,

    job_id: int = Form(...),

    conn=Depends(getDB)

):

    client_id = request.session.get("user_id")

    role = request.session.get("role")



    if role != "甲方":

        return RedirectResponse(url="/", status_code=302)



    await jobs.confirmJob(conn, job_id, client_id)

    return RedirectResponse(url=f"/read/{job_id}", status_code=302)



# 下載成果檔案

# 下載成果檔案
@app.get("/download/{job_id}")
async def download_file(job_id: int, conn=Depends(getDB)):
    
    # ✅ 修改後：改用複數版，並取出最後一筆
    deliverables = await jobs.getDeliverables(conn, job_id)
    
    # 判斷列表是否為空
    if not deliverables:
        return HTMLResponse("尚未上傳任何成果", status_code=404)

    # 取出最新的一筆 (List 的最後一個元素)
    deliverable = deliverables[-1] 

    # --- 以下邏輯保持不變 ---
    file_path = deliverable["file_path"]

    if not os.path.exists(file_path):

        return HTMLResponse("檔案不存在", status_code=404)

    filename = os.path.basename(file_path)

    return FileResponse(file_path, filename=filename)

# 🆕 新增：根據 deliverable_id (檔案流水號) 下載指定檔案
@app.get("/download_history/{deliverable_id}")
async def download_history_file(deliverable_id: int, conn=Depends(getDB)):
    # 直接查該筆上傳紀錄的檔案路徑
    async with conn.cursor() as cur:
        await cur.execute("SELECT file_path FROM deliverables WHERE id = %s", (deliverable_id,))
        record = await cur.fetchone()
    
    if not record or not os.path.exists(record["file_path"]):
        return HTMLResponse("❌ 檔案不存在或已遺失", status_code=404)

    filename = os.path.basename(record["file_path"])
    return FileResponse(record["file_path"], filename=filename)


# 下載需求文件

@app.get("/download_requirement/{job_id}")

async def download_requirement(job_id: int, conn=Depends(getDB)):

    async with conn.cursor() as cur:

        await cur.execute("SELECT requirement_file FROM jobs WHERE id=%s;", (job_id,))

        job = await cur.fetchone()



    if not job or not job["requirement_file"]:

        return HTMLResponse("⚠️ 此案件未提供需求文件", status_code=404)



    file_path = job["requirement_file"]

    if not os.path.exists(file_path):

        return HTMLResponse("❌ 找不到檔案", status_code=404)



    filename = os.path.basename(file_path)

    return FileResponse(file_path, filename=filename)



#甲方編輯案件(取得)

@app.get("/editJobForm/{job_id}")

async def edit_job_form(request: Request, job_id: int, conn=Depends(getDB)):

    role = request.session.get("role")

    if role != "甲方":

        return RedirectResponse(url="/", status_code=302)



    job = await jobs.getJob(conn, job_id)

    if not job:

        return HTMLResponse("❌ 找不到此案件", status_code=404)



    return templates.TemplateResponse("editJobForm.html", {

        "request": request,

        "job": job

    })





# 甲方確認結案

@app.post("/completeJob")

async def complete_job(

    request: Request,

    job_id: int = Form(...),

    conn=Depends(getDB)

):

    client_id = request.session.get("user_id")

    # 呼叫新的結案邏輯

    result = await jobs.completeJob(conn, job_id, client_id)
    await ratings_module.createRatingDeadline(conn, job_id)
    

    if result == "unresolved_issues":

        # 如果有未解決事項，導回頁面並顯示錯誤 (這裡簡單做，也可用 flash message)

        return HTMLResponse(

            f"<script>alert('❌ 無法結案！尚有「未解決」的 Issue 待處理。'); window.location.href='/read/{job_id}';</script>"

        )



    return RedirectResponse(url="/", status_code=302)

# 甲方退件（輸入原因）

@app.post("/rejectJob")

async def reject_job(

    request: Request,

    job_id: int = Form(...),

    reason: str = Form(...),

    conn=Depends(getDB)

):

    client_id = request.session.get("user_id")

    await jobs.rejectJob(conn, job_id, client_id, reason)

    return RedirectResponse(url=f"/read/{job_id}", status_code=302)







# === 乙方出價（修改，處理檔案上傳）===

@app.post("/bid")

async def bid_job(

    request: Request,

    job_id: int = Form(...),

    amount: int = Form(...),

    # ⚠️ 新增提案檔案，限 pdf 格式，故 accept 僅需檢查 pdf (前端仍需處理其他格式)

    proposal_file: UploadFile = File(None), 

    conn=Depends(getDB)

):

    bidder_id = request.session.get("user_id")

    role = request.session.get("role")



    if role != "乙方":

        return HTMLResponse("⚠️ 只有乙方可以競標", status_code=403)



    file_path = None

    if proposal_file and proposal_file.filename:

        # ⚠️ 檔案格式檢查：強制要求 PDF

        if not proposal_file.filename.lower().endswith('.pdf'):

            return HTMLResponse("⚠️ 提案計畫書必須是 PDF 格式。", status_code=400)

            

        upload_dir = "uploads/proposals" # 專門的提案檔案目錄

        os.makedirs(upload_dir, exist_ok=True)

        

        # 檔案名稱處理：使用 job_id, bidder_id, 時間戳，確保唯一性

        # 解決不同人上傳同名檔案不可覆蓋的問題

        safe_filename = proposal_file.filename.split('/')[-1].split('\\')[-1]

        safe_filename = f"job{job_id}_bidder{bidder_id}_{int(time.time())}_{safe_filename}"

        

        file_path = os.path.join(upload_dir, safe_filename)



        try:

            with open(file_path, "wb") as f:

                f.write(await proposal_file.read())

        except Exception as e:

            return HTMLResponse(f"⚠️ 檔案寫入失敗：{e}", status_code=500)

    else:

         # 提案計畫書為必傳

         return HTMLResponse("⚠️ 提案時需上傳提案計畫書。", status_code=400)



    # 呼叫 placeBid 傳入檔案路徑

    result = await jobs.placeBid(conn, job_id, bidder_id, amount, file_path)

    if result == "success":
        # 🔥🔥 新增：通知該案件的甲方 🔥🔥
        # 1. 先查出甲方是誰
        job_info = await jobs.getJob(conn, job_id)
        if job_info:
            target_client_id = job_info["client_id"]
            bidder_name = request.session.get("username")
            
            notification = {
                "type": "new_bid",
                "job_title": job_info["title"],
                "bidder": bidder_name,
                "amount": amount,
                "message": f"💰 您的案件「{job_info['title']}」有新的報價！(${amount})"
            }
            # 2. 只發送給這位甲方
            await manager.send_to_user(target_client_id, notification)


    if result == "too_low":

        return HTMLResponse("⚠️ 出價必須高於原始預算", status_code=400)

    elif result == "job_not_found":

        return HTMLResponse("⚠️ 找不到此案件", status_code=404)



    return RedirectResponse(url=f"/read/{job_id}", status_code=302)



# === 下載競標提案文件 (新增) ===

@app.get("/download_proposal/{bid_id}")

async def download_proposal(bid_id: int, conn=Depends(getDB)):

    # 從 bids 表中根據 bid_id 查 proposal_file

    async with conn.cursor() as cur:

        # ⚠️ 假設 getBids 返回的 row 中有 bid_id (jobs.py 中已修改)

        await cur.execute("SELECT proposal_file FROM bids WHERE id=%s;", (bid_id,))

        bid = await cur.fetchone()

        

    if not bid or not bid["proposal_file"]:

        return HTMLResponse("⚠️ 該報價未提供提案文件", status_code=404)



    file_path = bid["proposal_file"]

    if not os.path.exists(file_path):

        return HTMLResponse("❌ 找不到檔案", status_code=404)



    filename = os.path.basename(file_path)

    return FileResponse(file_path, filename=filename)



# === 甲方選擇乙方 ===

# main.py

@app.post("/chooseBid")
async def choose_bid(
    request: Request,
    job_id: int = Form(...),
    freelancer_id: int = Form(...),
    conn=Depends(getDB)
):
    role = request.session.get("role")
    if role != "甲方":
        return HTMLResponse("⚠️ 只有甲方可以選擇乙方", status_code=403)

    # 1. 執行資料庫更新 (選擇乙方)
    await jobs.chooseBid(conn, job_id, freelancer_id)

    # 🔥🔥 新增：發送獲選通知給乙方 🔥🔥
    # 先查詢案件標題，這樣通知比較清楚
    job_info = await jobs.getJob(conn, job_id)
    
    if job_info:
        notification = {
            "type": "bid_accepted",  # 這是新的通知類型
            "job_id": job_id,
            "message": f"🎉 恭喜！甲方已選擇您承接案件：「{job_info['title']}」"
        }
        # 指定發送給該位乙方 (freelancer_id)
        await manager.send_to_user(freelancer_id, notification)

    return RedirectResponse(url=f"/read/{job_id}", status_code=302)



#編輯按鍵更新資料

@app.post("/editJob")

async def edit_job(

    request: Request,

    job_id: int = Form(...),

    title: str = Form(...),

    content: str = Form(...),

    budget: int = Form(...),

    requirement_file: UploadFile = File(None),

    conn=Depends(getDB)

):

    user_id = request.session.get("user_id")

    role = request.session.get("role")



    if not user_id or role != "甲方":

        return HTMLResponse("❌ 沒有權限修改", status_code=403)



    file_path = None



    # ✅ 確保有上傳檔案且不是空檔案名

    if requirement_file and requirement_file.filename:

        upload_dir = "uploads"

        os.makedirs(upload_dir, exist_ok=True)



        # ✅ 用時間戳避免覆蓋同名檔案

        safe_filename = f"{int(time.time())}_{requirement_file.filename}"



        file_path = os.path.join(upload_dir, safe_filename)



        # ✅ 寫檔案（確保這裡的 file_path 是檔案，不是資料夾）

        try:

            with open(file_path, "wb") as f:

                f.write(await requirement_file.read())

        except PermissionError:

            return HTMLResponse("⚠️ 沒有權限寫入檔案（可能被 OneDrive 鎖住）", status_code=500)

        except Exception as e:

            return HTMLResponse(f"⚠️ 檔案寫入失敗：{e}", status_code=500)



    # ✅ 呼叫更新函式

    await jobs.updateJob(conn, job_id, title, content, budget, file_path)

    return RedirectResponse(url=f"/read/{job_id}", status_code=302)


# =============================

# 新增 Issue Tracker API 路由

# =============================

# === WebSocket Endpoint ===
@app.websocket("/ws/{job_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: int, user_id: int):
    await manager.connect(websocket, job_id)
    try:
        while True:
            # 保持連線，這裡我們主要靠 API 觸發廣播，所以這裡只需接收 keepalive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)

# === 新增：統一聊天發送 API (支援文字、貼圖、檔案) ===
@app.post("/api/chat/send")
async def send_chat_message(
    request: Request,
    job_id: int = Form(...),
    issue_id: int = Form(...),
    msg_type: str = Form(...), # 'text', 'sticker', 'image', 'file'
    content: str = Form(None), # 文字內容 或 貼圖ID
    file: UploadFile = File(None),
    conn=Depends(getDB)
):
    user_id = request.session.get("user_id")
    username = request.session.get("username")
    role = request.session.get("role")

    if not user_id:
        return JSONResponse({"error": "未登入"}, status_code=401)

    current_status = await jobs.getIssueStatus(conn, issue_id)
    if current_status == "已解決":
        return JSONResponse({"status": "error", "message": "❌ 此問題已結案，無法再傳送訊息"}, status_code=400)

    file_path = None
    filename = None
    display_content = content

    # 處理檔案上傳
    if msg_type in ['image', 'file'] and file and file.filename:
        upload_dir = "www/uploads/chat"
        os.makedirs(upload_dir, exist_ok=True)
        safe_filename = f"{int(time.time())}_{user_id}_{file.filename}"
        file_path = os.path.join(upload_dir, safe_filename)
        filename = file.filename

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 修正路徑以便前端存取 (移除 www 前綴)
        file_path = file_path.replace("www/", "")

        if not display_content:
            display_content = filename

    # 寫入資料庫
    result = await jobs.addIssueComment(
        conn, issue_id, user_id, display_content, 
        msg_type, file_path, filename
    )

    # 準備廣播訊息
    broadcast_data = {
        "issue_id": issue_id,
        "username": username,
        "role": role,
        "content": display_content,
        "msg_type": msg_type,
        "file_path": file_path,
        "filename": filename,
        "created_at": result["created_at"].strftime("%Y-%m-%d %H:%M")
    }

    # 透過 WebSocket 廣播給該 Job 的所有人
    await manager.broadcast(broadcast_data, job_id)

    return {"status": "ok"}

# 新增 Issue (甲方)

@app.post("/api/addIssue")
async def add_issue(
    request: Request,
    job_id: int = Form(...),
    title: str = Form(...),
    conn=Depends(getDB)
):
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    username = request.session.get("username") # 取得使用者名稱以便顯示
    
    # 權限檢查：只有甲方可以開 Issue
    if role != "甲方":
        return HTMLResponse("權限不足", status_code=403)
        
    # 1. 呼叫修改後的 createIssue (取得新 Issue 的 ID)
    new_issue = await jobs.createIssue(conn, job_id, title, user_id)

    # 2. 準備廣播資料 (通知所有人有個新 Issue 被建立了)
    broadcast_data = {
        "msg_type": "new_issue",  # 🔥 新的訊息類型
        "job_id": job_id,
        "issue_id": new_issue["id"],
        "title": title,
        "status": "未解決",
        "creator": username,
        "created_at": new_issue["created_at"].strftime("%Y-%m-%d %H:%M")
    }

    # 3. 透過 WebSocket 廣播
    await manager.broadcast(broadcast_data, job_id)

    # 4. 甲方自己刷新頁面 (Redirect)
    return RedirectResponse(url=f"/read/{job_id}", status_code=302)



# 新增留言 (甲乙雙方)

@app.post("/api/addComment")

async def add_comment(

    request: Request,

    job_id: int = Form(...),

    issue_id: int = Form(...),

    content: str = Form(...),

    conn=Depends(getDB)

):

    user_id = request.session.get("user_id")

    if not user_id:

        return RedirectResponse(url="/loginForm", status_code=302)

        

    await jobs.addIssueComment(conn, issue_id, user_id, content)

    return RedirectResponse(url=f"/read/{job_id}", status_code=302)



# 解決 Issue (甲方)
@app.post("/api/resolveIssue")
async def resolve_issue(
    request: Request,
    job_id: int = Form(...),
    issue_id: int = Form(...),
    conn=Depends(getDB)
):
    user_id = request.session.get("user_id")
    username = request.session.get("username")
    role = request.session.get("role")

    if role != "甲方":
        return HTMLResponse("權限不足", status_code=403)

    # 1. 呼叫新的 jobs.resolveIssue (會回傳新建立的留言資料)
    result = await jobs.resolveIssue(conn, issue_id, user_id, username)

    # 2. 準備廣播訊息
    broadcast_data = {
        "issue_id": issue_id,
        "username": "系統通知",  # 顯示名稱
        "role": "system",       # 角色設為 system
        "content": result["content"],
        "msg_type": "system",   # 關鍵類型
        "file_path": None,
        "filename": None,
        "created_at": result["created_at"].strftime("%H:%M") # 只取時間
    }

    # 3. 透過 WebSocket 廣播給所有人 (包含正在看頁面的乙方)
    await manager.broadcast(broadcast_data, job_id)

    # 4. 甲方自己會刷新頁面 (Redirect)，所以不用擔心重複顯示
    return RedirectResponse(url=f"/read/{job_id}", status_code=302)

# =============================
# 查看評價表單頁面
# =============================
@app.get("/api/ratingForm/{job_id}/{ratee_id}")
async def rating_form(
    request: Request,
    job_id: int,
    ratee_id: int,
    conn=Depends(getDB)
):
    """進入評價頁面"""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/loginForm", status_code=302)

    print(f"\n=== DEBUG rating_form ===")
    print(f"URL 參數 - job_id: {job_id}, ratee_id: {ratee_id}")

    # ✅ 關鍵：先查詢被評價者的基本信息
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, username, role FROM users WHERE id = %s",
            (ratee_id,)
        )
        ratee_user = await cur.fetchone()
    
    if not ratee_user:
        print(f"❌ 找不到被評價用戶: {ratee_id}")
        return HTMLResponse("❌ 被評價者不存在", status_code=404)
    
    print(f"✅ 找到被評價用戶: {ratee_user['username']}")

    # ✅ 驗證案件是否存在且狀態正確
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, status, client_id, freelancer_id FROM jobs WHERE id = %s",
            (job_id,)
        )
        job_info = await cur.fetchone()
    
    if not job_info:
        print(f"❌ 找不到案件: {job_id}")
        return HTMLResponse("❌ 案件不存在", status_code=404)
    
    if job_info["status"] != "已完成":
        print(f"❌ 案件狀態不是已完成: {job_info['status']}")
        return HTMLResponse(f"❌ 案件狀態必須是已完成（當前: {job_info['status']}）", status_code=403)
    
    print(f"✅ 案件狀態正確: {job_info['status']}")

    # ✅ 驗證評價期限
    deadline_info = await ratings_module.getRatingDeadline(conn, job_id)
    if not deadline_info:
        print(f"⚠️ 無評價期限記錄（首次評價？）")
    else:
        if datetime.now() > deadline_info["rating_deadline"]:
            print(f"❌ 評價期限已過")
            return HTMLResponse("❌ 評價期限已過", status_code=410)
        print(f"✅ 評價期限未過: {deadline_info['rating_deadline']}")

    # ✅ 獲取被評價者的評價統計
    rating_stats = await ratings_module.getUserRatingStats(conn, ratee_id)
    
    print(f"📊 評價統計: {rating_stats}")

    # ✅ 準備模板數據
    context = {
        "request": request,
        "job_id": job_id,
        "ratee_id": ratee_id,
        "ratee_name": ratee_user["username"],        # ✅ 這是關鍵
        "ratee_role": ratee_user["role"],            # ✅ 這是關鍵
        "avg_score": rating_stats["average_overall_rating"] if rating_stats else None,
        "total_ratings": rating_stats["total_ratings"] if rating_stats else 0
    }
    
    print(f"📋 模板上下文:")
    for key, value in context.items():
        if key != "request":
            print(f"  {key}: {value}")
    
    return templates.TemplateResponse("ratingForm.html", context)

# =============================
# 查看用戶評價頁面
# =============================
@app.get("/api/userProfile/{user_id}")
async def user_profile(
    request: Request,
    user_id: int,
    conn=Depends(getDB)
):
    """查看用戶的評價記錄與統計資訊"""
    async with conn.cursor() as cur:
        # 獲取用戶基本資訊
        await cur.execute(
            "SELECT id, username, role, created_at FROM users WHERE id = %s",
            (user_id,)
        )
        user = await cur.fetchone()
    
    if not user:
        return HTMLResponse("❌ 用戶不存在", status_code=404)

    # ✅ 新增：將 created_at 轉換為字符串
    user_data = dict(user)
    if user_data.get("created_at"):
        user_data["created_at_str"] = user_data["created_at"].strftime("%Y-%m-%d")
    else:
        user_data["created_at_str"] = "N/A"

    # 獲取用戶評價統計
    rating_stats = await jobs.getUserRatingStats(conn, user_id)
    if rating_stats:
        rating_stats = dict(rating_stats)
        
    # 獲取該用戶收到的所有評價
    async with conn.cursor() as cur:
        await cur.execute("""
            SELECT r.rater_id, u.username, r.dimension1_score, 
                   r.dimension2_score, r.dimension3_score, r.comment, r.created_at
            FROM ratings r
            JOIN users u ON r.rater_id = u.id
            WHERE r.ratee_id = %s
            ORDER BY r.created_at DESC
        """, (user_id,))
        reviews = await cur.fetchall()

    # ✅ 新增：將每條評價的 created_at 轉換為字符串
    reviews_data = []
    for review in reviews:
        review_dict = dict(review)
        if review_dict.get("created_at"):
            review_dict["created_at_str"] = review_dict["created_at"].strftime("%Y-%m-%d %H:%M")
        else:
            review_dict["created_at_str"] = "N/A"
        reviews_data.append(review_dict)

    # ✅ 新增：檢查「我」是否屏蔽了「這個人」
    current_user_id = request.session.get("user_id")
    is_blocked = False
    if current_user_id:
        is_blocked = await jobs.isBlocked(conn, current_user_id, user_id)

    return templates.TemplateResponse(
        "userProfile.html",
        {
            "request": request,
            "user": user_data,
            "rating_stats": rating_stats,
            "reviews": reviews_data,
            "avg_score": rating_stats["average_overall_rating"] if rating_stats else None,
            "total_ratings": rating_stats["total_ratings"] if rating_stats else 0,
            "is_blocked": is_blocked,   # 👈 傳入前端
            "current_user_id": current_user_id # 👈 確保前端知道我有沒有登入
        }
    )

@app.post("/api/toggleBlock")
async def toggle_block_user(
    request: Request,
    blocked_id: int = Form(...),
    conn=Depends(getDB)
):
    blocker_id = request.session.get("user_id")
    if not blocker_id:
        return HTMLResponse("請先登入", status_code=401)
    
    if blocker_id == blocked_id:
         return HTMLResponse("不能屏蔽自己", status_code=400)

    status = await jobs.toggleBlockUser(conn, blocker_id, blocked_id)
    
    # 操作完成後重新整理頁面
    return RedirectResponse(url=f"/api/userProfile/{blocked_id}", status_code=302)

# 取得我的黑名單列表 (用於設定頁面管理)
async def getBlockedUsers(conn, blocker_id):
    async with conn.cursor() as cur:
        sql = """
            SELECT u.id, u.username, u.role, b.created_at
            FROM blocked_users b
            JOIN users u ON b.blocked_id = u.id
            WHERE b.blocker_id = %s
            ORDER BY b.created_at DESC;
        """
        await cur.execute(sql, (blocker_id,))
        return await cur.fetchall()
    
# main.py

@app.get("/editProfile")
async def edit_profile_form(request: Request, conn=Depends(getDB)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/loginForm", status_code=302)

    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM users WHERE id = %s;", (user_id,))
        user = await cur.fetchone()

    if not user:
        return HTMLResponse("找不到使用者", status_code=404)

    # ✅ 新增：取得我封鎖的使用者列表
    blocked_list = await jobs.getBlockedUsers(conn, user_id)

    return templates.TemplateResponse("editProfile.html", {
        "request": request,
        "user": user,
        "blocked_users": blocked_list  # 👈 傳給前端
    })