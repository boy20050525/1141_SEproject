# jobs.py
# =============================
# 資料庫操作層 (Data Access Layer)
# =============================
# 功能說明：
# - 提供工作 (Job) 的 CRUD 與查詢功能
# - 與 main.py、upload.py 共同運作
# - 對應資料表：jobs, users, quotations, deliverables
# =============================

from psycopg_pool import AsyncConnectionPool

# ---------------------------------
# 1️⃣ 取得全部工作清單 (首頁)
# ---------------------------------
async def getJobList(conn):
    async with conn.cursor() as cur:
        sql = """
        SELECT 
            j.id, j.title, j.content, j.status, j.budget, j.price,
            c.username AS client_name,
            f.username AS freelancer_name,
            j.created_at
        FROM jobs j
        LEFT JOIN users c ON j.client_id = c.id
        LEFT JOIN users f ON j.freelancer_id = f.id
        ORDER BY j.id ASC;
        """
        await cur.execute(sql)
        rows = await cur.fetchall()
        return rows
    
# 依狀態取得工作清單
async def getJobsByStatus(conn, status):
    async with conn.cursor() as cur:
        await cur.execute("""
            SELECT 
                j.*, 
                c.username AS client_name, 
                f.username AS freelancer_name
            FROM jobs j
            LEFT JOIN users c ON j.client_id = c.id
            LEFT JOIN users f ON j.freelancer_id = f.id
            WHERE j.status = %s
            ORDER BY j.id DESC;
        """, (status,))
        result = await cur.fetchall()
    return result



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
async def getAvailableJobs(conn):
    async with conn.cursor() as cur:
        sql = """
        SELECT 
            j.id, j.title, j.status, j.budget, j.content,
            c.username AS client_name,
            j.created_at
        FROM jobs j
        LEFT JOIN users c ON j.client_id = c.id
        WHERE j.status IN ('新工作', '報價中')
        ORDER BY j.id ASC;
        """
        await cur.execute(sql)
        rows = await cur.fetchall()
        return rows


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


