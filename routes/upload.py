
# routes/upload.py
# =============================
# 處理檔案上傳的 API
# =============================
# 功能：
# - 安全地接收上傳檔案
# - 儲存到 /www/uploads 目錄
# - 更新 deliverables 資料表
# - 同步更新 jobs 狀態為「上傳成果」
# =============================

from fastapi import APIRouter, File, UploadFile, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse
import os
import re

from db import getDB
import jobs  # ✅ 改成新的模組（取代 posts.py）

router = APIRouter()

# =============================
# 安全檔名檢查函式
# =============================
def safeFilename(filename: str):
    ALLOWED_EXTENSIONS = {".txt", ".pdf", ".png", ".jpg", ".jpeg", ".zip"}
    name, ext = os.path.splitext(filename)

    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不允許的檔案類型")

    # 取代非法字元
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', filename)
    safe = re.sub(r'_+', '_', safe)

    # 限制長度
    return safe[:255]


# =============================
# 上傳檔案 API
# =============================
@router.post("/upload")
async def upload_file(
    request: Request,
    job_id: int = Form(...),
    uploadedFile: UploadFile = File(...),
    conn=Depends(getDB)
):
    """
    乙方上傳結案成果：
    - 檢查檔名
    - 儲存檔案到 /www/uploads/
    - 寫入 deliverables 資料表
    - 更新 jobs.status = '上傳成果'
    """

    # 1️⃣ 檢查與安全化檔名
    safe_name = safeFilename(uploadedFile.filename)
    upload_dir = "www/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, safe_name)

    # 2️⃣ 儲存檔案內容
    contents = await uploadedFile.read()
    with open(file_path, "wb") as f:
        f.write(contents)

    # 3️⃣ 取得當前使用者 ID
    user_id = request.session.get("user_id")
    if not user_id:
         raise HTTPException(status_code=403, detail="未登入")

    # 4️⃣ 儲存上傳紀錄 & 更新狀態
    async with conn.cursor() as cur:
        sql1 = """
            INSERT INTO deliverables (job_id, file_path, uploaded_by)
            VALUES (%s, %s, %s);
        """
        await cur.execute(sql1, (job_id, file_path, user_id)) # ✅ 使用真正的 user_id

        # 更新工作狀態
        sql2 = """
            UPDATE jobs
            SET status = '上傳成果', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
        """
        await cur.execute(sql2, (job_id,))

        # 🚨 關鍵修正：提交資料庫異動
        await conn.commit()

    return RedirectResponse(url=f"/read/{job_id}", status_code=302)


# =============================
# 分段上傳 (進階，可保留)
# =============================
@router.post("/upload/chunked")
async def chunk_upload_file(fileField: UploadFile = File(...)):
    """
    範例：分段上傳，限制檔案大小
    """
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    CHUNK_SIZE = 1024 * 1024  # 1MB
    safeFn = safeFilename(fileField.filename)
    upload_path = f"www/uploads/{safeFn}"
    total_size = 0

    try:
        with open(upload_path, "wb") as buffer:
            while True:
                chunk = await fileField.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    buffer.close()
                    os.remove(upload_path)
                    raise HTTPException(status_code=413, detail="檔案過大")
                buffer.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上傳失敗: {str(e)}")

    return {"filename": safeFn, "size_bytes": total_size}

