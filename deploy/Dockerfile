# ============================================
# Dockerfile — 高考志愿填报 App 后端
# ============================================
# 构建: docker build -t gaokao-app .
# 运行: docker run -d --env-file .env -p 8000:8000 gaokao-app

FROM python:3.13-slim

# ── 系统依赖 ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# ── 工作目录 ──
WORKDIR /app

# ── 先复制依赖文件，利用 Docker 缓存层 ──
COPY backend/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir pymysql  # MySQL support (optional, won't break SQLite)

# ── 复制后端代码 ──
COPY backend/ .

# ── 复制前端文件（FastAPI StaticFiles 托管）─ ──
# 前端文件在 backend 的上级目录 gaokao-app/
# Docker 中我们把它们放到 /app/frontend/
COPY css/ /app/frontend/css/
COPY js/ /app/frontend/js/
COPY data/ /app/frontend/data/
COPY index.html /app/frontend/index.html

# ── 修正 BASE_DIR 指向前端目录 ──
# main.py 中 BASE_DIR = parent of backend dir = gaokao-app/
# 在 Docker 中 backend 在 /app，前端在 /app/frontend
# 需要创建 symlink 或修改路径
# 这里我们通过环境变量让 main.py 能找到前端文件
ENV FRONTEND_DIR=/app/frontend

# ── 日志目录 ──
RUN mkdir -p /app/logs

# ── 数据库目录（SQLite）──
# MySQL 环境下不需要此步
VOLUME /app/data

# ── 非 root 用户 ──
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app
USER appuser

# ── 端口 ──
EXPOSE 8000

# ── 启动命令 ──
# 生产环境用多 worker，不开启 reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
