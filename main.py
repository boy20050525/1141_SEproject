# main.py
from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sessionLogin import router as login_router
from fastapi import File, UploadFile

import os
import time

from db import getDB
import jobs  # 對應 jobs.py（原本的 posts.py 改名後）

# 載入 routes 子模組
from routes.upload import router as upload_router
from routes.dbQuery import router as db_router

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
        job_list = await jobs.getJobsByStatus(conn, selected_status)
    else:
        job_list = await jobs.getJobList(conn)

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




# === 顯示案件詳情 (含競標清單 + 上傳檔案資訊) ===
@app.get("/read/{id}")
async def readJob(request: Request, id: int, conn=Depends(getDB)):
    # 從 jobs.py 抓取案件資訊
    jobDetail = await jobs.getJob(conn, id)

    # 競標清單（乙方報價）
    bids = await jobs.getBids(conn, id)

    # 上傳成果（乙方已交付的檔案資訊）
    deliverable = await jobs.getDeliverable(conn, id)

    # === 新增：取得該案件的 Issue 列表 ===
    issue_list = await jobs.getIssues(conn, id)

    # 傳到模板 jobDetail.html
    return templates.TemplateResponse(
        "jobDetail.html",
        {
            "request": request,
            "job": jobDetail,
            "bids": bids,
            "deliverable": deliverable,
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
    requirement_file: UploadFile = File(None),   # 👈 新增上傳檔案
    conn=Depends(getDB)
):
    user_id = request.session.get("user_id")
    role = request.session.get("role")

    if not user_id or role != "甲方":
        raise HTTPException(status_code=403, detail="只有甲方可新增工作")

    file_path = None
    if requirement_file:
        upload_dir = "uploads/requirements"
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, requirement_file.filename)
        with open(file_path, "wb") as f:
            f.write(await requirement_file.read())

    await jobs.addJob(conn, title, content, budget, user_id, file_path)
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
# 登入 / 登出
# =============================
@app.get("/loginForm")
async def login_form(request: Request):
    return templates.TemplateResponse("loginForm.html", {"request": request})

@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    conn=Depends(getDB)
):
    async with conn.cursor() as cur:
        sql = "SELECT id, role FROM users WHERE username=%s AND password=%s"
        await cur.execute(sql, (username, password))
        user = await cur.fetchone()

    if user:
        request.session["user_id"] = user["id"]
        request.session["role"] = user["role"]

        if user["role"] == "甲方":
            return RedirectResponse(url="/dashboard_client", status_code=302)
        else:
            return RedirectResponse(url="/dashboard_freelancer", status_code=302)
    else:
        return HTMLResponse("帳號或密碼錯誤，<a href='/loginForm'>返回登入</a>", status_code=401)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
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
    available_jobs = await jobs.getAvailableJobs(conn)
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
@app.get("/download/{job_id}")
async def download_file(job_id: int, conn=Depends(getDB)):
    deliverable = await jobs.getDeliverable(conn, job_id)
    if not deliverable:
        return HTMLResponse("尚未上傳任何成果", status_code=404)

    file_path = deliverable["file_path"]
    if not os.path.exists(file_path):
        return HTMLResponse("檔案不存在", status_code=404)

    filename = os.path.basename(file_path)
    return FileResponse(file_path, filename=filename)

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



# === 乙方出價 ===
@app.post("/bid")
async def bid_job(
    request: Request,
    job_id: int = Form(...),
    amount: int = Form(...),
    conn=Depends(getDB)
):
    bidder_id = request.session.get("user_id")
    role = request.session.get("role")

    if role != "乙方":
        return HTMLResponse("⚠️ 只有乙方可以競標", status_code=403)

    result = await jobs.placeBid(conn, job_id, bidder_id, amount)
    if result == "too_low":
        return HTMLResponse("⚠️ 出價必須高於原始預算", status_code=400)
    elif result == "job_not_found":
        return HTMLResponse("⚠️ 找不到此案件", status_code=404)

    return RedirectResponse(url=f"/read/{job_id}", status_code=302)


# === 甲方選擇乙方 ===
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

    await jobs.chooseBid(conn, job_id, freelancer_id)
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
    
    # 權限檢查：只有甲方可以開 Issue
    if role != "甲方":
        return HTMLResponse("權限不足", status_code=403)
        
    await jobs.createIssue(conn, job_id, title, user_id)
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
    role = request.session.get("role")
    if role != "甲方":
        return HTMLResponse("權限不足", status_code=403)

    await jobs.resolveIssue(conn, issue_id)
    return RedirectResponse(url=f"/read/{job_id}", status_code=302)