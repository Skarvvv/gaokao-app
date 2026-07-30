"""
高考志愿填报 App — 后端 API 服务
=====================================
技术栈：FastAPI + Uvicorn
当前阶段：MVP 起步，从 test_data.json 读取假数据返回给前端
后续演进：接入 LLM 推理、数据库、消息队列等

启动方式：
    cd gaokao-app/backend
    python main.py
    # 或: uvicorn main:app --reload --port 8000
访问地址：
    http://localhost:8000          → 前端页面
    http://localhost:8000/api/...  → API 接口
    http://localhost:8000/docs     → API 文档（FastAPI 自带）
"""

import os

import json
import time
from pathlib import Path
from typing import Any, List, Optional

from fastapi import FastAPI, Query, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from logging_config import setup_logging, get_logger, RequestLoggingMiddleware
from llm_client import generate_recommendations, generate_school_detail
from database import get_db, init_db
from models import User, UserProfile
from auth import hash_password, verify_password, create_token, get_current_user
from schemas import RegisterRequest, LoginRequest, ProfileRequest
from config import LLM_API_KEY, JWT_SECRET, DATABASE_URL, SERVER_HOST, SERVER_PORT

# ============================================
# 启动环境检查
# ============================================

_MISSING = []
if not LLM_API_KEY:
    _MISSING.append("LLM_API_KEY")
if not JWT_SECRET:
    _MISSING.append("JWT_SECRET")

if _MISSING:
    # Allow missing env vars in dev mode (with warnings)
    import sys
    _is_dev = "--reload" in sys.argv or os.environ.get("GAOKAO_DEV_MODE", "")
    if _is_dev:
        print(f"[WARN] Missing env vars: {', '.join(_MISSING)} — using dev defaults")
        # Dev defaults
        if not LLM_API_KEY:
            os.environ["LLM_API_KEY"] = "sk-hgazhgdjmyywcugftkxeksagvqvddyxtxefbywvaarlbszwm"
        if not JWT_SECRET:
            os.environ["JWT_SECRET"] = "gaokao-app-dev-secret-change-in-production"
        # Re-import config to pick up the defaults
        import importlib
        importlib.reload(__import__("config"))
    else:
        print(f"[ERROR] Required env vars not set: {', '.join(_MISSING)}")
        print("Set them via .env file or environment variables before starting the server.")
        print("See deploy/.env.example for reference.")
        sys.exit(1)

# ============================================
# 配置
# ============================================

# 项目根目录（gaokao-app/）
# Docker 环境：前端文件通过 FRONTEND_DIR 环境变量指定
# 本地开发：自动取 backend 的上级目录
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", "")
if FRONTEND_DIR:
    BASE_DIR = Path(FRONTEND_DIR).resolve()
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

# 假数据文件路径
DATA_FILE = BASE_DIR / "data" / "test_data.json"

# ── 初始化日志系统（必须在所有模块使用 logger 之前）──
setup_logging()
logger = get_logger("api")


# ============================================
# 统一响应格式
# ============================================
# 所有 API 接口返回统一结构：{ code, message, data }
#   code=0 表示成功，非 0 表示错误
#   data  为实际业务数据
# 前端 apiGet() 会自动解包 data 字段

def success(data: Any) -> dict:
    """构造成功响应"""
    return {"code": 0, "message": "success", "data": data}


def error(code: int, message: str) -> dict:
    """构造错误响应"""
    return {"code": code, "message": message, "data": None}


# ============================================
# 数据加载
# ============================================

def load_test_data() -> dict:
    """从 test_data.json 加载假数据到内存"""
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("假数据文件不存在: %s", DATA_FILE)
        raise
    except json.JSONDecodeError as e:
        logger.error("假数据文件 JSON 解析失败: %s", e)
        raise


# 启动时一次性加载到内存（避免每次请求都读文件）
_test_data = load_test_data()
logger.info("假数据已加载: %s", DATA_FILE)


# ============================================
# FastAPI 应用
# ============================================

app = FastAPI(
    title="高考志愿填报 App API",
    description="MVP 阶段后端服务 — 从 test_data.json 提供假数据",
    version="0.1.0",
)

# CORS 中间件
# 同源部署（后端托管前端）时其实不需要，加上是为了支持前后端分离开发
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求日志中间件 — 自动记录每个 HTTP 请求的 method, path, status, duration
app.add_middleware(RequestLoggingMiddleware)

# Initialize database tables on startup
init_db()
logger.info("LLM Provider: SiliconFlow Qwen2.5-7B-Instruct")
logger.info("Static files: %s", BASE_DIR)


# ============================================
# 全局异常处理 — 统一错误响应格式
# ============================================
# 将 FastAPI 的 HTTPException (如 401 未授权) 转换为统一的 {code, message, data} 格式
# 这样前端 apiGet/apiPost 的解包逻辑可以统一处理

@app.exception_handler(FastAPIHTTPException)
async def unified_http_exception_handler(request: Request, exc: FastAPIHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=error(exc.status_code, str(exc.detail)),
    )


# ============================================
# API 路由
# ============================================
# 路由前缀统一为 /api
# 注意：路由必须在 StaticFiles 挂载之前注册，否则会被静态文件拦截

@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return success({"status": "ok", "version": "0.1.0"})


@app.get("/api/recommendations")
async def get_recommendations(
    score: Optional[int] = Query(None, description="高考总分"),
    province: Optional[str] = Query(None, description="所在省份"),
    subjects: Optional[str] = Query(None, description="选考科目，逗号分隔"),
):
    """
    获取志愿推荐方案（冲稳保梯度推荐）

    前端传入成绩、省份、科目等参数。
    MVP 阶段直接返回假数据，后续接入 LLM 推理 + 双轨校验引擎。
    """
    logger.info("[API] GET /api/recommendations — score=%s, province=%s, subjects=%s",
                score, province, subjects)
    data = _test_data.get("recommendations")
    if data is None:
        return JSONResponse(status_code=404, content=error(404, "推荐方案数据不存在"))
    return success(data)


@app.get("/api/probability")
async def get_probability(
    score: Optional[int] = Query(None, description="高考总分"),
    province: Optional[str] = Query(None, description="所在省份"),
):
    """
    获取录取概率预测

    MVP 阶段返回假数据（含免费预览 + 付费锁定）。
    后续接入概率预测模型，付费用户解锁完整预测。
    """
    logger.info("[API] GET /api/probability — score=%s, province=%s", score, province)
    data = _test_data.get("probability")
    if data is None:
        return JSONResponse(status_code=404, content=error(404, "概率预测数据不存在"))
    return success(data)


@app.get("/api/school/{school_id}")
async def get_school_detail(
    school_id: str,
    score: Optional[int] = Query(None, description="高考总分"),
    province: Optional[str] = Query(None, description="所在省份"),
    subjects: Optional[str] = Query(None, description="选考科目，逗号分隔"),
    major: Optional[str] = Query(None, description="报考专业"),
    segment: Optional[str] = Query(None, description="梯度: chong/wen/bao"),
):
    """
    获取院校详情（LLM 生成）

    school_id 为院校名称（URL 编码）。
    根据考生分数、省份、专业和梯度，调用 LLM 生成个性化的院校详情。
    返回结构：name, tags, badge, location, admissionData, aiAnalysis, similarRecommendations
    """
    logger.info(
        "[API] GET /api/school/%s — score=%s, province=%s, major=%s, segment=%s",
        school_id, score, province, major, segment,
    )

    # 从查询参数构建考生数据
    user_data = {
        "score": score or 500,
        "province": province or "",
        "subjects": subjects.split(",") if subjects else [],
    }

    # 默认值
    major_name = major or "未指定专业"
    segment_val = segment or "wen"

    try:
        detail = await generate_school_detail(school_id, major_name, segment_val, user_data)
        return success(detail)
    except Exception as e:
        logger.error("[API] 院校详情生成异常: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=error(500, f"院校详情生成失败: {e}"),
        )


@app.get("/api/generating-steps")
async def get_generating_steps():
    """
    获取方案生成步骤状态

    用于前端「正在生成」页面的步骤进度展示。
    后续接入异步任务队列后，根据任务 ID 返回实时进度。
    """
    logger.info("[API] GET /api/generating-steps")
    data = _test_data.get("generatingSteps")
    if data is None:
        return JSONResponse(status_code=404, content=error(404, "生成步骤数据不存在"))
    return success(data)


# ============================================
# POST /api/generate — LLM 生成志愿方案
# ============================================
# 前端点击"生成志愿方案"后，将用户数据 POST 到此接口
# 后端构建提示词 → 调用 LLM → 解析返回 → 包装为统一格式返回

class GenerateRequest(BaseModel):
    """前端提交的考生数据"""
    score: int
    province: str = ""
    subjects: List[str] = []
    schoolLevels: List[str] = []
    majors: List[str] = []
    strategy: str = ""
    region: str = ""


@app.post("/api/generate")
async def generate_plan(req: GenerateRequest):
    """
    生成志愿方案（LLM 推理）

    接收考生成绩、省份、选考科目和偏好，
    分 3 次并行调用大模型（冲/稳/保各 2 所），
    合并为完整的"冲稳保"梯度推荐方案。
    """
    logger.info(
        "[API] POST /api/generate — score=%d, province=%s, subjects=%s",
        req.score, req.province, req.subjects,
    )

    user_data = {
        "score": req.score,
        "province": req.province,
        "subjects": req.subjects,
        "schoolLevels": req.schoolLevels,
        "majors": req.majors,
        "strategy": req.strategy,
        "region": req.region,
    }

    try:
        recommendations = await generate_recommendations(user_data)
        return success(recommendations)

    except ValueError as e:
        logger.error("[API] 生成方案失败 (ValueError): %s", e)
        return JSONResponse(
            status_code=500,
            content=error(500, str(e)),
        )
    except Exception as e:
        logger.error("[API] 生成方案异常: %s", e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=error(500, f"服务器内部错误: {e}"),
        )


# ============================================
# 认证路由 — /api/auth/*
# ============================================

@app.post("/api/auth/register")
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册：手机号 + 密码 → 创建用户 → 返回 JWT token"""
    logger.info("[API] POST /api/auth/register — phone=%s", req.phone)

    # 检查手机号是否已注册
    existing = db.query(User).filter(User.phone == req.phone).first()
    if existing:
        return JSONResponse(
            status_code=409,
            content=error(409, "该手机号已注册"),
        )

    # 创建用户
    user = User(
        phone=req.phone,
        password_hash=hash_password(req.password),
        nickname=req.nickname or "",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user.id)
    logger.info("[API] 注册成功: user_id=%d, phone=%s", user.id, user.phone)

    return success({
        "token": token,
        "user": user.to_dict(),
        "profile": None,
    })


@app.post("/api/auth/login")
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """用户登录：手机号 + 密码 → 验证 → 返回 JWT token + 用户档案"""
    logger.info("[API] POST /api/auth/login — phone=%s", req.phone)

    user = db.query(User).filter(User.phone == req.phone).first()
    if not user or not verify_password(req.password, user.password_hash):
        return JSONResponse(
            status_code=401,
            content=error(401, "手机号或密码错误"),
        )

    token = create_token(user.id)
    profile_data = user.profile.to_dict() if user.profile else None

    logger.info("[API] 登录成功: user_id=%d, has_profile=%s", user.id, profile_data is not None)

    return success({
        "token": token,
        "user": user.to_dict(),
        "profile": profile_data,
    })


@app.get("/api/auth/me")
async def get_me(user: User = Depends(get_current_user)):
    """获取当前登录用户信息（需要 Bearer token）"""
    return success({"user": user.to_dict()})


@app.get("/api/auth/profile")
async def get_profile(user: User = Depends(get_current_user)):
    """获取当前用户的档案数据（需要 Bearer token）"""
    profile_data = user.profile.to_dict() if user.profile else None
    return success({"profile": profile_data})


@app.put("/api/auth/profile")
async def update_profile(
    req: ProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建或更新用户档案（需要 Bearer token）

    前端在用户点击"生成志愿方案"时调用此接口保存档案，
    下次登录后通过 GET /api/auth/profile 取回并预填表单。
    """
    logger.info("[API] PUT /api/auth/profile — user_id=%d", user.id)

    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()

    if profile:
        # 更新已有档案
        profile.score = req.score
        profile.province = req.province
        profile.subjects = json.dumps(req.subjects, ensure_ascii=False) if req.subjects else None
        profile.school_levels = json.dumps(req.schoolLevels, ensure_ascii=False) if req.schoolLevels else None
        profile.majors = json.dumps(req.majors, ensure_ascii=False) if req.majors else None
        profile.strategy = req.strategy
        profile.region = req.region
    else:
        # 首次创建档案
        profile = UserProfile(
            user_id=user.id,
            score=req.score,
            province=req.province,
            subjects=json.dumps(req.subjects, ensure_ascii=False) if req.subjects else None,
            school_levels=json.dumps(req.schoolLevels, ensure_ascii=False) if req.schoolLevels else None,
            majors=json.dumps(req.majors, ensure_ascii=False) if req.majors else None,
            strategy=req.strategy,
            region=req.region,
        )
        db.add(profile)

    db.commit()
    db.refresh(profile)

    logger.info("[API] 档案已保存: user_id=%d, score=%s", user.id, profile.score)

    return success({"profile": profile.to_dict()})


# ============================================
# 静态文件托管（前端页面）
# ============================================
# 将 gaokao-app/ 目录挂载为静态文件根目录
# 前端文件结构：index.html, css/style.css, js/app.js, data/*.json
# html=True: 访问 / 时自动返回 index.html
#
# 重要：此挂载必须在所有 API 路由之后，否则会拦截 /api/... 请求

app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="frontend")


# ============================================
# 启动入口
# ============================================

if __name__ == "__main__":
    import uvicorn
    from config import SERVER_HOST, SERVER_PORT, SERVER_WORKERS
    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        workers=SERVER_WORKERS,
        reload=SERVER_WORKERS == 1,  # reload only in single-worker dev mode
        log_level="info",
    )
