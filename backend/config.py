"""Configuration
=================
LLM settings + Database + JWT Auth

Environment variables (required for production):
  - LLM_API_KEY:   SiliconFlow / DeepSeek API key
  - JWT_SECRET:    Must be a strong random string (not the default!)
  - DATABASE_URL:  MySQL connection string for production
                    e.g. mysql+pymysql://user:pass@localhost:3306/gaokao_app

Defaults:
  - LLM:      SiliconFlow (free Qwen2.5-7B, OpenAI-compatible)
  - Database: SQLite (zero-install, perfect for development)
  - Auth:     JWT (HS256, 7-day expiry)

To switch to MySQL:
  1. pip install pymysql
  2. Set DATABASE_URL env var or change the default below
  3. No other code changes needed (SQLAlchemy ORM is database-agnostic)
"""

import os

# ── Dev mode flag ──
# GAOKAO_DEV_MODE=true allows missing env vars to fall back to dev defaults.
# Production MUST NOT set this flag — missing env vars will cause startup failure.
_IS_DEV = os.environ.get("GAOKAO_DEV_MODE", "").lower() in ("true", "1", "yes")

# ── LLM Provider ──
# SiliconFlow: free models available, new users get 20M tokens
# Production: MUST set LLM_API_KEY via env var
# Dev mode: falls back to a shared free-tier key
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
if not LLM_API_KEY and _IS_DEV:
    LLM_API_KEY = "sk-hgazhgdjmyywcugftkxeksagvqvddyxtxefbywvaarlbszwm"

# SiliconFlow endpoint (OpenAI-compatible)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")

# ── Request tuning ──
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.7"))
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "4000"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))  # seconds

# ── Alternative: DeepSeek (better Chinese, but needs paid credits) ──
# Set env vars: LLM_BASE_URL=https://api.deepseek.com LLM_MODEL=deepseek-chat


# ── Database ──
# SQLite for development (auto-created in backend/ dir)
# PostgreSQL for production — Supabase free tier 500MB:
#   ⚠️ Use the POOLER connection string (IPv4), NOT the direct connection (IPv6)!
#   Direct:  postgresql://postgres:[PWD]@db.xxxxxx.supabase.co:5432/postgres     ← IPv6, fails on Render/Heroku
#   Pooler:  postgresql://postgres.xxxxxx:[PWD]@aws-0-[region].pooler.supabase.com:6543/postgres  ← IPv4, works everywhere
#   Find it: Supabase Dashboard → Project Settings → Database → Connection string → "Connection pooling" / "Transaction pooler"
# MySQL also supported:
#   mysql+pymysql://user:password@localhost:3306/gaokao_app
_DB_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(_DB_DIR, 'gaokao.db')}",
)

# ── JWT Auth ──
# Production: MUST set JWT_SECRET via env var
# Dev mode: falls back to a dev-only secret
JWT_SECRET = os.environ.get("JWT_SECRET", "")
if not JWT_SECRET and _IS_DEV:
    JWT_SECRET = "gaokao-app-dev-secret-change-in-production"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))

# ── Server ──
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
# Render.com provides $PORT env var; default to 8000 for local dev
SERVER_PORT = int(os.environ.get("PORT", os.environ.get("SERVER_PORT", "8000")))
SERVER_WORKERS = int(os.environ.get("SERVER_WORKERS", "1"))  # >1 requires MySQL
