# routes/ratings.py
# =============================
# 評價機制 (Ratings System)
# =============================

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
from db import getDB

router = APIRouter()
templates = Jinja2Templates(directory="templates")

def normalize_score(value):
    try:
        value = int(value)
        if 1 <= value <= 5:
            return value
        return 1
    except:
        return 1
# =============================
# 1️⃣ 提交評價
# =============================
async def submitRating(conn, job_id, rater_id, ratee_id, rater_role, 
                       dim1_score, dim2_score, dim3_score, comment=""):
    """
    提交評價 - 必須在期限內
    """
    
    # 安全處理評分
    dim1_score = normalize_score(dim1_score)
    dim2_score = normalize_score(dim2_score)
    dim3_score = normalize_score(dim3_score)

    async with conn.cursor() as cur:
        
        # ✅ 驗證評價是否在期限內（嚴格檢查）
        await cur.execute("""
            SELECT rating_deadline FROM rating_deadlines WHERE job_id = %s
        """, (job_id,))
        deadline_info = await cur.fetchone()
        
        if not deadline_info:
            print(f"❌ 找不到評價期限: job_id={job_id}")
            return "no_deadline"
        
        # ✅ 檢查是否已過期
        current_time = datetime.now()
        deadline_time = deadline_info["rating_deadline"]
        
        print(f"評價時間檢查:")
        print(f"  當前時間: {current_time}")
        print(f"  截止時間: {deadline_time}")
        print(f"  剩餘時間: {deadline_time - current_time}")
        
        if current_time > deadline_time:
            print(f"❌ 評價期限已過: 超過 {current_time - deadline_time}")
            return "rating_expired"
        
        time_remaining = deadline_time - current_time
        print(f"✅ 評價仍在期限內，剩餘時間: {time_remaining}")
        
        # 插入或更新評價記錄
        sql = """
        INSERT INTO ratings 
        (job_id, rater_id, ratee_id, rater_role, dimension1_score, 
         dimension2_score, dimension3_score, comment)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(job_id, rater_id) 
        DO UPDATE SET 
            dimension1_score = EXCLUDED.dimension1_score,
            dimension2_score = EXCLUDED.dimension2_score,
            dimension3_score = EXCLUDED.dimension3_score,
            comment = EXCLUDED.comment,
            updated_at = CURRENT_TIMESTAMP;
        """

        await cur.execute(sql, (
            job_id, rater_id, ratee_id, rater_role,
            dim1_score, dim2_score, dim3_score, comment
        ))
        
        # 更新該用戶的評價統計
        await updateUserRatingStats(conn, ratee_id)
        
        # 標記評價已完成
        if rater_role == "甲方":
            await cur.execute(
                "UPDATE rating_deadlines SET client_rated = TRUE WHERE job_id = %s",
                (job_id,)
            )
        else:
            await cur.execute(
                "UPDATE rating_deadlines SET freelancer_rated = TRUE WHERE job_id = %s",
                (job_id,)
            )
        
        await conn.commit()
        print(f"✅ 評價已提交: rater_id={rater_id}, ratee_id={ratee_id}")
        return "success"


# =============================
# 2️⃣ 更新用戶評價統計
# =============================
async def updateUserRatingStats(conn, user_id):
    """根據所有評價重新計算該用戶的平均分"""
    async with conn.cursor() as cur:
        # 獲取該用戶的角色
        await cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        user = await cur.fetchone()
        if not user:
            return
        
        role = user["role"]
        
        # 計算平均分（根據角色選擇評價維度）
        if role == "甲方":
            sql = """
            SELECT 
                COUNT(*) as total_ratings,
                ROUND(AVG(dimension1_score)::numeric, 2) as avg_requirement_rationality,
                ROUND(AVG(dimension2_score)::numeric, 2) as avg_verification_difficulty,
                ROUND(AVG(dimension3_score)::numeric, 2) as avg_client_cooperation,
                ROUND((
                    AVG(dimension1_score) + AVG(dimension2_score) + AVG(dimension3_score)
                ) / 3::numeric, 2) as avg_overall
            FROM ratings 
            WHERE ratee_id = %s AND rater_role = '乙方'
            """
        else:  # 乙方
            sql = """
            SELECT 
                COUNT(*) as total_ratings,
                ROUND(AVG(dimension1_score)::numeric, 2) as avg_output_quality,
                ROUND(AVG(dimension2_score)::numeric, 2) as avg_execution_efficiency,
                ROUND(AVG(dimension3_score)::numeric, 2) as avg_freelancer_cooperation,
                ROUND((
                    AVG(dimension1_score) + AVG(dimension2_score) + AVG(dimension3_score)
                ) / 3::numeric, 2) as avg_overall
            FROM ratings 
            WHERE ratee_id = %s AND rater_role = '甲方'
            """
        
        await cur.execute(sql, (user_id,))
        stats = await cur.fetchone()
        
        if not stats or stats["total_ratings"] == 0:
            # 沒有評價，設為 NULL
            await cur.execute(
                "UPDATE user_rating_stats SET total_ratings = 0 WHERE user_id = %s",
                (user_id,)
            )
        else:
            if role == "甲方":
                update_sql = """
                UPDATE user_rating_stats 
                SET avg_requirement_rationality = %s,
                    avg_verification_difficulty = %s,
                    avg_client_cooperation = %s,
                    average_overall_rating = %s,
                    total_ratings = %s
                WHERE user_id = %s
                """
                await cur.execute(update_sql, (
                    stats["avg_requirement_rationality"],
                    stats["avg_verification_difficulty"],
                    stats["avg_client_cooperation"],
                    stats["avg_overall"],
                    stats["total_ratings"],
                    user_id
                ))
            else:
                update_sql = """
                UPDATE user_rating_stats 
                SET avg_output_quality = %s,
                    avg_execution_efficiency = %s,
                    avg_freelancer_cooperation = %s,
                    average_overall_rating = %s,
                    total_ratings = %s
                WHERE user_id = %s
                """
                await cur.execute(update_sql, (
                    stats["avg_output_quality"],
                    stats["avg_execution_efficiency"],
                    stats["avg_freelancer_cooperation"],
                    stats["avg_overall"],
                    stats["total_ratings"],
                    user_id
                ))
        
        await conn.commit()

# =============================
# 3️⃣ 查詢用戶平均評價
# =============================
async def getUserRatingStats(conn, user_id):
    """獲取用戶的平均評價與質性評論"""
    async with conn.cursor() as cur:
        # 先取得使用者角色
        await cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        user = await cur.fetchone()
        if not user:
            return None
        
        role = user["role"]
        
        # 根據角色計算平均分
        if role == "甲方":
            sql = """
            SELECT 
                COUNT(*) AS total_ratings,
                ROUND(AVG(dimension1_score)::numeric, 2) AS avg_requirement_rationality,
                ROUND(AVG(dimension2_score)::numeric, 2) AS avg_verification_difficulty,
                ROUND(AVG(dimension3_score)::numeric, 2) AS avg_client_cooperation,
                ROUND((AVG(dimension1_score)+AVG(dimension2_score)+AVG(dimension3_score))/3::numeric, 2) AS average_overall_rating
            FROM ratings
            WHERE ratee_id = %s AND rater_role = '乙方'
            """
        else:  # 乙方
            sql = """
            SELECT 
                COUNT(*) AS total_ratings,
                ROUND(AVG(dimension1_score)::numeric, 2) AS avg_output_quality,
                ROUND(AVG(dimension2_score)::numeric, 2) AS avg_execution_efficiency,
                ROUND(AVG(dimension3_score)::numeric, 2) AS avg_freelancer_cooperation,
                ROUND((AVG(dimension1_score)+AVG(dimension2_score)+AVG(dimension3_score))/3::numeric, 2) AS average_overall_rating
            FROM ratings
            WHERE ratee_id = %s AND rater_role = '甲方'
            """
        
        await cur.execute(sql, (user_id,))
        stats = await cur.fetchone()
        return stats



# =============================
# 4️⃣ 查詢該工作案件的所有評價
# =============================
async def getJobRatings(conn, job_id):
    """查詢某個工作案件的評價記錄"""
    async with conn.cursor() as cur:
        sql = """
        SELECT 
            r.id, r.rater_id, r.ratee_id, r.rater_role,
            u_rater.username as rater_name,
            u_ratee.username as ratee_name,
            r.dimension1_score, r.dimension2_score, r.dimension3_score,
            r.comment, r.created_at
        FROM ratings r
        JOIN users u_rater ON r.rater_id = u_rater.id
        JOIN users u_ratee ON r.ratee_id = u_ratee.id
        WHERE r.job_id = %s
        ORDER BY r.created_at DESC
        """
        await cur.execute(sql, (job_id,))
        return await cur.fetchall()

# =============================
# 5️⃣ 建立評價期限 (工作結案後)
# =============================
async def createRatingDeadline(conn, job_id):
    """
    在工作結案時建立評價期限
    評價截止日期：結案後 1 天（可修改）
    """
    async with conn.cursor() as cur:
        # 如果要改為其他時間，修改這裡：
        # - 1小時：timedelta(hours=1)
        # - 3天：timedelta(days=3)
        # - 7天：timedelta(days=7)
        deadline = datetime.now() + timedelta(days=1)
        
        sql = """
        INSERT INTO rating_deadlines (job_id, rating_deadline)
        VALUES (%s, %s)
        ON CONFLICT(job_id) DO UPDATE 
        SET rating_deadline = %s
        """
        await cur.execute(sql, (job_id, deadline, deadline))
        await conn.commit()
        
        print(f"✅ 建立評價期限: job_id={job_id}, deadline={deadline}")


# =============================
# 6️⃣ 查詢評價期限狀態
# =============================
async def getRatingDeadline(conn, job_id):
    """查詢該工作案件的評價期限與完成狀況"""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT * FROM rating_deadlines WHERE job_id = %s",
            (job_id,)
        )
        result = await cur.fetchone()
        
        if result:
            # 過期檢查
            is_expired = datetime.now() > result["rating_deadline"]
            print(f"評價期限檢查: job_id={job_id}, deadline={result['rating_deadline']}, expired={is_expired}")
        
        return result


# =============================
# API 路由：查看評價表單頁面
# =============================
@router.get("/ratingForm/{job_id}/{ratee_id}")
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

    # 取得登入使用者資料
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, username, role FROM users WHERE id = %s",
            (user_id,)
        )
        user = await cur.fetchone()

        # 取得被評價者資料
        await cur.execute(
            "SELECT id, username, role FROM users WHERE id = %s",
            (ratee_id,)
        )
        ratee = await cur.fetchone()

    if not ratee:
        return HTMLResponse("❌ 被評價者不存在", status_code=404)

    # ✅ 驗證評價期限
    deadline_info = await getRatingDeadline(conn, job_id)
    if not deadline_info:
        print(f"⚠️ 無評價期限記錄")
        return HTMLResponse("❌ 此案件無評價期限或尚未結案", status_code=403)

    current_time = datetime.now()
    deadline_time = deadline_info["rating_deadline"]
    time_remaining = deadline_time - current_time
    
    # ✅ 計算剩餘時間（天、小時、分鐘）
    total_seconds = time_remaining.total_seconds()
    days = int(total_seconds // 86400)
    hours = int((total_seconds % 86400) // 3600)
    minutes = int((total_seconds % 3600) // 60)
    
    if current_time > deadline_time:
        print(f"❌ 評價期限已過")
        return HTMLResponse("❌ 評價期限已過，無法評價", status_code=410)
    
    print(f"✅ 評價期限未過，剩餘: {days}天 {hours}小時 {minutes}分鐘")

    # 取得被評價者的統計資料
    rating_stats = await getUserRatingStats(conn, ratee_id)

    # 確保 rating_stats 是 dict，即使沒有記錄也給預設值
    if not rating_stats:
        rating_stats = {
            "average_overall_rating": None,
            "total_ratings": 0
        }

    return templates.TemplateResponse(
        "ratingForm.html",
        {
            "request": request,
            "user": user,         
            "ratee": ratee,       
            "job_id": job_id,

            # 前端直接用 avg_score 與 total_ratings
            "avg_score": rating_stats["average_overall_rating"],
            "total_ratings": rating_stats["total_ratings"],

            "deadline": deadline_time.strftime("%Y-%m-%d %H:%M:%S"),
            "time_remaining_days": days,
            "time_remaining_hours": hours,
            "time_remaining_minutes": minutes,
            "time_remaining_text": f"{days}天 {hours}小時 {minutes}分鐘"
        }
    )

# =============================
# API 路由：提交評價
# =============================
@router.post("/submitRating")
async def submit_rating_api(
    request: Request,
    job_id: str = Form(...),
    ratee_id: str = Form(...),
    dimension1_score: str = Form(...),
    dimension2_score: str = Form(...),
    dimension3_score: str = Form(...),
    comment: str = Form(""),
    conn=Depends(getDB)
):
    """提交評價的 API 端點"""
    rater_id = request.session.get("user_id")
    role = request.session.get("role")
    
    if not rater_id:
        raise HTTPException(status_code=403, detail="未登入")
    
    try:
        # ✅ 轉換字符串為整數
        job_id = int(job_id)
        ratee_id = int(ratee_id)
        dim1 = int(dimension1_score)
        dim2 = int(dimension2_score)
        dim3 = int(dimension3_score)
        
        # ✅ 驗證分數範圍
        if dim1 < 1 or dim1 > 5 or dim2 < 1 or dim2 > 5 or dim3 < 1 or dim3 > 5:
            raise HTTPException(status_code=400, detail="評分必須在 1-5 之間")
        
        result = await submitRating(
            conn, job_id, rater_id, ratee_id, role,
            dim1, dim2, dim3, comment
        )
        
        if result == "rating_expired":
            raise HTTPException(status_code=410, detail="評價期限已過")
        
        return {"status": "success"}
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"數據格式錯誤：{str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提交失敗：{str(e)}")


