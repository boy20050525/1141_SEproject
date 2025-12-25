# jobs.py
# =============================
# 資料庫操作層 (Data Access Layer)
# =============================
# 功能說明：
# - 提供工作 (Job) 的 CRUD 與查詢功能
# - 與 main.py、upload.py 共同運作
# - 對應資料表：jobs, users, quotations, deliverables
# =============================

import secrets
from psycopg_pool import AsyncConnectionPool
from datetime import datetime, timedelta

# ---------------------------------
# 重設密碼功能
# ---------------------------------
# 1️⃣ 透過 Email 找使用者 (維持不變)
async def getUserByEmail(conn, email):
    async with conn.cursor() as cur:
        # 根據您的 users 資料表
        await cur.execute("SELECT id, username FROM users WHERE email = %s;", (email,))
        return await cur.fetchone()

# 2️⃣ 儲存重設 Token (修改：存入 password_reset_tokens 表)
async def saveResetToken(conn, user_id):
    token = secrets.token_urlsafe(32) # 產生安全亂碼
    expires = datetime.now() + timedelta(minutes=15)
    
    async with conn.cursor() as cur:
        # ⚠️ 修改：使用 INSERT 寫入獨立資料表
        sql = """
        INSERT INTO password_reset_tokens (user_id, token, expires_at)
        VALUES (%s, %s, %s);
        """
        await cur.execute(sql, (user_id, token, expires))
        await conn.commit()
    return token

# 3️⃣ 驗證 Token 是否有效 (修改：查詢 password_reset_tokens 表)
async def verifyToken(conn, token):
    async with conn.cursor() as cur:
        # 查詢 token 是否存在且尚未過期
        sql = """
        SELECT user_id FROM password_reset_tokens 
        WHERE token = %s AND expires_at > CURRENT_TIMESTAMP;
        """
        await cur.execute(sql, (token,))
        row = await cur.fetchone()
        
        if row:
            # 如果 Token 有效，順便抓取使用者資料回傳 (方便後續處理)
            user_id = row["user_id"]
            await cur.execute("SELECT id, username FROM users WHERE id = %s;", (user_id,))
            return await cur.fetchone()
        return None

# 4️⃣ 重設密碼並清除 Token (修改：刪除 password_reset_tokens 紀錄)
async def resetPassword(conn, user_id, new_password):
    async with conn.cursor() as cur:
        # 1. 更新使用者密碼
        sql_update = "UPDATE users SET password = %s WHERE id = %s;"
        await cur.execute(sql_update, (new_password, user_id))
        
        # 2. 刪除該使用者所有的重設 Token (避免舊連結被重複使用)
        sql_delete = "DELETE FROM password_reset_tokens WHERE user_id = %s;"
        await cur.execute(sql_delete, (user_id,))
        
        await conn.commit()
    return True

# ---------------------------------
# 1️⃣ 取得全部工作清單 (首頁)
# ---------------------------------
# 1. 修改 getJobList (取得全部)
async def getJobList(conn, current_user_id=None): # 👈 多傳入 user_id
    async with conn.cursor() as cur:
        sql = """
        SELECT 
            j.id, j.title, j.content, j.status, j.budget, j.price,
            c.username AS client_name, c.id AS client_id,
            f.username AS freelancer_name,
            j.created_at
        FROM jobs j
        LEFT JOIN users c ON j.client_id = c.id
        LEFT JOIN users f ON j.freelancer_id = f.id
        WHERE 1=1
        """
        params = []

        # ✅ 屏蔽邏輯：雙向過濾
        if current_user_id:
            sql += """
                AND j.client_id NOT IN (
                    SELECT blocked_id FROM blocked_users WHERE blocker_id = %s
                )
                AND j.client_id NOT IN (
                    SELECT blocker_id FROM blocked_users WHERE blocked_id = %s
                )
            """
            params.extend([current_user_id, current_user_id])
            
        sql += " ORDER BY j.id ASC;"
        
        await cur.execute(sql, tuple(params))
        return await cur.fetchall()

# 2. 修改 getJobsByStatus (依狀態篩選，也要過濾黑名單！)
async def getJobsByStatus(conn, status, current_user_id=None): # 👈 這裡也要多傳 user_id
    async with conn.cursor() as cur:
        sql = """
            SELECT 
                j.*, 
                c.username AS client_name, c.id AS client_id,
                f.username AS freelancer_name
            FROM jobs j
            LEFT JOIN users c ON j.client_id = c.id
            LEFT JOIN users f ON j.freelancer_id = f.id
            WHERE j.status = %s
        """
        params = [status] # 先放入狀態參數

        # ✅ 這裡也要加上一樣的屏蔽邏輯
        if current_user_id:
            sql += """
                AND j.client_id NOT IN (
                    SELECT blocked_id FROM blocked_users WHERE blocker_id = %s
                )
                AND j.client_id NOT IN (
                    SELECT blocker_id FROM blocked_users WHERE blocked_id = %s
                )
            """
            params.extend([current_user_id, current_user_id])
            
        sql += " ORDER BY j.id DESC;"

        await cur.execute(sql, tuple(params))
        return await cur.fetchall()



# ---------------------------------
# 2️⃣ 取得單一工作詳細資料
# ---------------------------------
async def getJob(conn, job_id):
    async with conn.cursor() as cur:
        sql = """
        SELECT 
            j.id, j.title, j.content, j.status, j.budget, j.price,
            j.deadline,
            j.requirement_file,
            j.requirement_file,
            j.client_id,         
            j.freelancer_id, 
            c.username AS client_name,
            f.username AS freelancer_name,
            j.created_at
        FROM jobs j
        LEFT JOIN users c ON j.client_id = c.id
        LEFT JOIN users f ON j.freelancer_id = f.id
        WHERE j.id = %s;
        """
        await cur.execute(sql, (job_id,))
        row = await cur.fetchone()
        return row


# ---------------------------------
# 3️⃣ 新增工作 (甲方建立)
# ---------------------------------
async def addJob(conn, title, content, budget, client_id, requirement_file=None, deadline=None):
    async with conn.cursor() as cur:
        sql = """
        INSERT INTO jobs (title, content, budget, client_id, status, requirement_file, deadline)
        VALUES (%s, %s, %s, %s, '新工作', %s, %s);
        """
        # ⚠️ 修復處：確保傳入 7 個參數
        await cur.execute(sql, (title, content, budget, client_id, requirement_file, deadline))
        await conn.commit()
        return True
    
# ---------------------------------
# 4️⃣ 刪除工作 (甲方刪除)
# ---------------------------------
async def deleteJob(conn, job_id, client_id):
    async with conn.cursor() as cur:
        # 僅能刪除自己發的案子
        sql = "DELETE FROM jobs WHERE id=%s AND client_id=%s;"
        await cur.execute(sql, (job_id, client_id))
        return True


# ---------------------------------
# 5️⃣ 查詢甲方發的工作 (Dashboard)
# ---------------------------------
async def getJobsByClient(conn, client_id):
    async with conn.cursor() as cur:
        sql = """
        SELECT 
            j.id, j.title, j.status, j.budget, j.price,
            f.username AS freelancer_name,
            j.created_at
        FROM jobs j
        LEFT JOIN users f ON j.freelancer_id = f.id
        WHERE j.client_id = %s
        ORDER BY j.id ASC;
        """
        await cur.execute(sql, (client_id,))
        rows = await cur.fetchall()
        return rows


# ---------------------------------
# 6️⃣ 查詢乙方接的案子 (Dashboard)
# ---------------------------------
async def getJobsByFreelancer(conn, freelancer_id):
    async with conn.cursor() as cur:
        sql = """
        SELECT 
            j.id, j.title, j.status, j.budget, j.price,
            c.username AS client_name,
            j.created_at
        FROM jobs j
        LEFT JOIN users c ON j.client_id = c.id
        WHERE j.freelancer_id = %s
        ORDER BY j.id ASC;
        """
        await cur.execute(sql, (freelancer_id,))
        rows = await cur.fetchall()
        return rows


# ---------------------------------
# 7️⃣ 查詢乙方可報價的工作 (尚未有人接案)
# ---------------------------------
async def getAvailableJobs(conn, current_user_id=None): # 👈 多傳入 current_user_id
    async with conn.cursor() as cur:
        sql = """
        SELECT 
            j.id, j.title, j.status, j.budget, j.content,
            c.username AS client_name, c.id AS client_id,
            j.created_at
        FROM jobs j
        LEFT JOIN users c ON j.client_id = c.id
        WHERE j.status IN ('新工作', '報價中')
        """
        params = []

        # ✅ 同樣的過濾邏輯
        if current_user_id:
            sql += """
                AND j.client_id NOT IN (
                    SELECT blocked_id FROM blocked_users WHERE blocker_id = %s
                )
                AND j.client_id NOT IN (
                    SELECT blocker_id FROM blocked_users WHERE blocked_id = %s
                )
            """
            params.extend([current_user_id, current_user_id])

        sql += " ORDER BY j.id ASC;"
        
        await cur.execute(sql, tuple(params))
        return await cur.fetchall()


# ---------------------------------
# 8️⃣ 甲方選擇乙方承接 (更新 freelancer_id 與狀態)
# ---------------------------------
async def assignFreelancer(conn, job_id, freelancer_id, price):
    async with conn.cursor() as cur:
        sql = """
        UPDATE jobs
        SET freelancer_id = %s, price = %s, status = '進行中', updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """
        await cur.execute(sql, (freelancer_id, price, job_id))
        return True




# ---------------------------------
# 🔟 查詢上傳成果（deliverables）
# ---------------------------------
async def getDeliverables(conn, job_id):
    async with conn.cursor() as cur:
        sql = """
        SELECT 
            d.id, d.file_path, d.uploaded_by, u.username AS uploader_name, d.uploaded_at, d.reject_reason
        FROM deliverables d
        LEFT JOIN users u ON d.uploaded_by = u.id
        WHERE d.job_id = %s
        ORDER BY d.uploaded_at ASC;
        """
        await cur.execute(sql, (job_id,))
        rows = await cur.fetchall()
        return rows


# 乙方提出接案申請
async def requestJob(conn, job_id, freelancer_id):
    async with conn.cursor() as cur:
        sql = """
        UPDATE jobs
        SET freelancer_id = %s, status = '待確認'
        WHERE id = %s AND freelancer_id IS NULL;
        """
        await cur.execute(sql, (freelancer_id, job_id))
        await conn.commit()
        return True


# 甲方確認接案
async def confirmJob(conn, job_id, client_id):
    async with conn.cursor() as cur:
        sql = """
        UPDATE jobs
        SET status = '進行中'
        WHERE id = %s AND client_id = %s AND status = '待確認';
        """
        await cur.execute(sql, (job_id, client_id))
        await conn.commit()
        return True

# 甲方確認結案
async def completeJob(conn, job_id, client_id):
    # 1. 先檢查是否有未解決的 Issue
    if await hasUnresolvedIssues(conn, job_id):
        return "unresolved_issues" # 回傳錯誤標記

    async with conn.cursor() as cur:
        sql = """
        UPDATE jobs
        SET status = '已完成', updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND client_id = %s;
        """
        await cur.execute(sql, (job_id, client_id))
        await conn.commit()
        return True


# 甲方退件
async def rejectJob(conn, job_id, client_id, reason):
    async with conn.cursor() as cur:
        # 更新 job 狀態
        sql1 = """
        UPDATE jobs
        SET status = '進行中', updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND client_id = %s;
        """
        await cur.execute(sql1, (job_id, client_id))

        # 更新 deliverable 的退件原因
        sql2 = """
        UPDATE deliverables
        SET reject_reason = %s
        WHERE job_id = %s;
        """
        await cur.execute(sql2, (reason, job_id))

        await conn.commit()
        return True


# 查詢乙方上傳的交付檔案（含退件理由）
async def getDeliverable(conn, job_id):
    async with conn.cursor() as cur:
        sql = """
        SELECT file_path, uploaded_by, reject_reason
        FROM deliverables
        WHERE job_id = %s
        ORDER BY id DESC LIMIT 1;
        """
        await cur.execute(sql, (job_id,))
        row = await cur.fetchone()
        return row
    
# === 取得競標列表（修改，新增 proposal_file 欄位）===
async def getBids(conn, job_id):
    async with conn.cursor() as cur:
        sql = """
        SELECT 
            b.id AS bid_id, 
            u.id AS bidder_id,
            u.username, 
            b.amount, 
            b.created_at,
            b.proposal_file  /* ⚠️ 新增 proposal_file */
        FROM bids b
        JOIN users u ON b.bidder_id = u.id
        WHERE b.job_id = %s
        ORDER BY b.amount DESC;
        """
        await cur.execute(sql, (job_id,))
        rows = await cur.fetchall()
        return rows


# === 乙方出價（修改，新增 proposal_file 參數）===
async def placeBid(conn, job_id, bidder_id, amount, proposal_file=None): # 👈 新增 proposal_file
    async with conn.cursor() as cur:
        # 1️⃣ 查案件預算
        await cur.execute("SELECT budget FROM jobs WHERE id=%s;", (job_id,))
        job = await cur.fetchone()
        if not job:
            return "job_not_found"
        if amount <= job["budget"]:
            return "too_low"

        # 2️⃣ 刪除該乙方舊報價
        await cur.execute("DELETE FROM bids WHERE job_id=%s AND bidder_id=%s;", (job_id, bidder_id))

        # 3️⃣ 插入新報價（修改 SQL，新增 proposal_file）
        # ⚠️ 假設 bids 資料表有 proposal_file 欄位
        await cur.execute("""
            INSERT INTO bids (job_id, bidder_id, amount, proposal_file) 
            VALUES (%s, %s, %s, %s);  
        """, (job_id, bidder_id, amount, proposal_file)) # 👈 傳入 proposal_file

        # ✅ 4️⃣ 更新 job 狀態為「報價中」
        await cur.execute("""
            UPDATE jobs
            SET status = '待確認'
            WHERE id = %s AND status = '新工作';
        """, (job_id,))

        await conn.commit()
        return "success"



# === 甲方選擇得標乙方 ===
async def chooseBid(conn, job_id, freelancer_id):
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE jobs SET freelancer_id=%s, status='進行中' WHERE id=%s;",
            (freelancer_id, job_id)
        )
        # 清除所有競標紀錄（可保留歷史）
        await cur.execute("DELETE FROM bids WHERE job_id=%s;", (job_id,))
        await conn.commit()

#甲方更新案件
async def updateJob(conn, job_id, title, content, budget, requirement_file=None):
    async with conn.cursor() as cur:
        if requirement_file:
            sql = """
            UPDATE jobs 
            SET title=%s, content=%s, budget=%s, requirement_file=%s
            WHERE id=%s;
            """
            await cur.execute(sql, (title, content, budget, requirement_file, job_id))
        else:
            sql = """
            UPDATE jobs 
            SET title=%s, content=%s, budget=%s
            WHERE id=%s;
            """
            await cur.execute(sql, (title, content, budget, job_id))

        await conn.commit()


# =============================
# Issue Tracker 相關功能
# =============================

# 修改：取得某案件的所有 Issue (需包含 msg_type, file_path, filename)
async def getIssues(conn, job_id):
    async with conn.cursor() as cur:
        # 1. 先抓出所有 Issues
        sql_issues = """
            SELECT i.*, u.username AS creator_name 
            FROM issues i
            LEFT JOIN users u ON i.created_by = u.id
            WHERE i.job_id = %s
            ORDER BY i.id ASC;
        """
        await cur.execute(sql_issues, (job_id,))
        issues = await cur.fetchall()

        # 2. 為每個 Issue 抓取 Comments (新增選取新欄位)
        for issue in issues:
            sql_comments = """
                SELECT c.*, u.username, u.role
                FROM issue_comments c
                LEFT JOIN users u ON c.user_id = u.id
                WHERE c.issue_id = %s
                ORDER BY c.created_at ASC;
            """
            await cur.execute(sql_comments, (issue["id"],))
            issue["comments"] = await cur.fetchall()
            
        return issues

# 新增 Issue
async def createIssue(conn, job_id, title, user_id):
    async with conn.cursor() as cur:
        sql = """
            INSERT INTO issues (job_id, title, created_by, status)
            VALUES (%s, %s, %s, '未解決');
        """
        await cur.execute(sql, (job_id, title, user_id))
        await conn.commit()

# 新增留言
async def addIssueComment(conn, issue_id, user_id, content, msg_type='text', file_path=None, filename=None):
    async with conn.cursor() as cur:
        sql = """
            INSERT INTO issue_comments (issue_id, user_id, content, msg_type, file_path, filename, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id, created_at;
        """
        # 注意：content 若是貼圖，存貼圖代碼；若是檔案，存說明文字
        await cur.execute(sql, (issue_id, user_id, content, msg_type, file_path, filename))
        new_comment = await cur.fetchone()
        await conn.commit()
        return new_comment # 回傳新建立的資料以便 WebSocket 廣播

# 將 Issue 標記為已解決
async def resolveIssue(conn, issue_id):
    async with conn.cursor() as cur:
        sql = "UPDATE issues SET status='已解決' WHERE id=%s;"
        await cur.execute(sql, (issue_id,))
        await conn.commit()

# 檢查是否有「未解決」的 Issue
async def hasUnresolvedIssues(conn, job_id):
    async with conn.cursor() as cur:
        sql = "SELECT COUNT(*) AS count FROM issues WHERE job_id=%s AND status='未解決';"
        await cur.execute(sql, (job_id,))
        result = await cur.fetchone()
        return result["count"] > 0
async def getUserRatingStats(conn, user_id):
    """獲取用戶的平均評價統計"""
    from routes.ratings import getUserRatingStats as get_stats
    return await get_stats(conn, user_id)


async def getRatingDeadline(conn, job_id):
    """獲取評價期限"""
    from routes.ratings import getRatingDeadline as get_deadline
    return await get_deadline(conn, job_id)

async def getDeliverable(conn, job_id):
    """查詢乙方上傳的交付檔案（含退件理由）"""
    async with conn.cursor() as cur:
        sql = """
        SELECT file_path, uploaded_by, reject_reason
        FROM deliverables
        WHERE job_id = %s
        ORDER BY id DESC LIMIT 1;
        """
        await cur.execute(sql, (job_id,))
        row = await cur.fetchone()
        return row
    
# =============================
# 🚫 屏蔽用戶相關功能
# =============================

# 1. 切換屏蔽狀態 (屏蔽/解屏蔽)
async def toggleBlockUser(conn, blocker_id, blocked_id):
    async with conn.cursor() as cur:
        # 先檢查是否已經屏蔽
        await cur.execute(
            "SELECT id FROM blocked_users WHERE blocker_id=%s AND blocked_id=%s",
            (blocker_id, blocked_id)
        )
        record = await cur.fetchone()

        if record:
            # 如果已經屏蔽 -> 解除屏蔽 (刪除紀錄)
            await cur.execute(
                "DELETE FROM blocked_users WHERE id=%s",
                (record["id"],)
            )
            await conn.commit()
            return "unblocked"
        else:
            # 如果還沒屏蔽 -> 新增屏蔽
            await cur.execute(
                "INSERT INTO blocked_users (blocker_id, blocked_id) VALUES (%s, %s)",
                (blocker_id, blocked_id)
            )
            await conn.commit()
            return "blocked"

# 2. 檢查是否已屏蔽 (用於前端顯示按鈕狀態)
async def isBlocked(conn, blocker_id, blocked_id):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT 1 FROM blocked_users WHERE blocker_id=%s AND blocked_id=%s",
            (blocker_id, blocked_id)
        )
        return await cur.fetchone() is not None
    
# 3. 取得我的黑名單列表 (用於設定頁面管理)
async def getBlockedUsers(conn, blocker_id):
    async with conn.cursor() as cur:
        # 關聯 users 表，抓出被封鎖者的名字和角色
        sql = """
            SELECT u.id, u.username, u.role, b.created_at
            FROM blocked_users b
            JOIN users u ON b.blocked_id = u.id
            WHERE b.blocker_id = %s
            ORDER BY b.created_at DESC;
        """
        await cur.execute(sql, (blocker_id,))
        return await cur.fetchall()