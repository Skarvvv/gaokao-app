# 免费云部署指南

> 目标：零成本把高考志愿填报 App（前端 + Python 后端）部署到公网，获得 HTTPS 访问地址。

---

## 方案对比

| 平台 | 免费额度 | 内存 | 休眠策略 | Docker | 推荐指数 |
|------|---------|------|---------|--------|---------|
| **Render.com** | 750h/月 | 512MB | 15 分钟无访问后休眠 | ✅ | ⭐⭐⭐⭐⭐ |
| **Hugging Face Spaces** | 无限（免费版） | 16GB | 48 小时无访问后休眠 | ✅ | ⭐⭐⭐⭐ |
| **Google Cloud Run** | 200 万请求/月 | 可选 | 按请求启动，无休眠等待 | ✅ | ⭐⭐⭐ |

---

## 方案 A：Render.com（推荐 — 最简单）

### 前置条件
- GitHub 账号（https://github.com/signup）
- Render 账号（https://render.com/signup，可用 GitHub 登录）

### Step 1：把代码推到 GitHub

```bash
# 进入项目目录
cd gaokao-app

# 初始化 Git 仓库
git init
git add .
git commit -m "Initial commit: gaokao zhiyuan app"

# 在 GitHub 上创建新仓库（不要勾选 README）
# 然后推送
git remote add origin https://github.com/<你的用户名>/gaokao-app.git
git branch -M main
git push -u origin main
```

> 如果不想用命令行，可以直接在 GitHub 网页上传文件：
> 1. 新建仓库 → 上传文件 → 把 `gaokao-app/` 里的文件拖进去
> 2. 注意：`backend/` 目录下的 `__pycache__/`、`*.pyc`、`*.db`、`logs/` 不要上传

### Step 2：在 Render 创建 Web Service

1. 登录 https://dashboard.render.com
2. 点 **New +** → **Web Service**
3. 连接你的 GitHub 账号，选择 `gaokao-app` 仓库
4. 填写配置：
   - **Name**: `gaokao-zhiyuan-app`（或任意名称）
   - **Runtime**: Docker
   - **Dockerfile Path**: `deploy/Dockerfile.render`
   - **Instance Type**: Free
5. 点 **Create Web Service**

### Step 3：设置环境变量

在 Render 控制台的 **Environment** 标签页添加：

**快速测试模式**（推荐先用这个）：

| Key | Value | 说明 |
|-----|-------|------|
| `GAOKAO_DEV_MODE` | `true` | 开发模式，自动填充默认 API Key 和 JWT Secret |

**正式测试模式**（更安全）：

| Key | Value | 说明 |
|-----|-------|------|
| `LLM_API_KEY` | `sk-你的SiliconFlow密钥` | SiliconFlow API Key |
| `JWT_SECRET` | `openssl rand -hex 32` 的输出 | JWT 签名密钥 |

> 两种模式二选一。快速测试模式最省事，直接就能跑。

### Step 4：等待部署完成

- Render 会自动拉取代码、构建 Docker 镜像、启动服务
- 首次构建约 5-10 分钟
- 构建完成后，Render 会分配一个 URL：`https://gaokao-zhiyuan-app.onrender.com`
- 访问这个 URL 即可使用完整的 App（前端 + 后端 + LLM）

### Step 5：验证

访问 `https://你的URL/api/health`，应返回：
```json
{"code": 0, "message": "success", "data": {"status": "ok", "version": "0.1.0"}}
```

### 注意事项
- **休眠**：免费版 15 分钟无访问后自动休眠，下次访问时会自动唤醒（约 30 秒）
- **数据**：SQLite 数据在重新部署后会丢失（免费版无持久化磁盘）。测试无妨，正式使用需配 MySQL
- **构建缓存**：第二次起构建会快很多（Docker layer cache）

---

## 方案 B：Hugging Face Spaces（资源更充足）

### 前置条件
- Hugging Face 账号（https://huggingface.co/join）

### Step 1：创建 Space

1. 访问 https://huggingface.co/new-space
2. 填写：
   - **Space name**: `gaokao-app`
   - **SDK**: Docker
   - **License**: 任意
3. 点 **Create Space**

### Step 2：上传文件

在你的 Space 页面点 **Files** → **Add file** → 依次上传：

```
gaokao-app/
├── backend/          # 整个目录（不要上传 __pycache__, *.db, logs/）
├── css/
├── data/
├── js/
├── index.html
└── deploy/Dockerfile.hf  ← 重命名为 Dockerfile 放在根目录
```

同时创建一个 `README.md`（Space 根目录），内容：
```markdown
---
title: Gaokao Zhiyuan App
emoji: 🎓
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---
```

### Step 3：设置环境变量

在 Space 的 **Settings** → **Repository secrets** 中添加：
- `GAOKAO_DEV_MODE` = `true`

### Step 4：等待构建

HF Spaces 会自动构建并启动。访问地址：`https://你的用户名-gaokao-app.hf.space`

### 优势
- 16GB 内存（Render 免费版只有 512MB）
- 2 vCPU
- 不限制每月时长
- 48 小时无访问才休眠（Render 是 15 分钟）

---

## 方案 C：Google Cloud Run（最灵活）

### 前置条件
- Google Cloud 账号（https://cloud.google.com/free）
- 安装 gcloud CLI（https://cloud.google.com/sdk/docs/install）

### Step 1：构建并推送镜像

```bash
# 配置 gcloud
gcloud auth login
gcloud config set project 你的项目ID

# 配置 Docker 认证
gcloud auth configure-docker

# 构建镜像
cd gaokao-app
docker build -f deploy/Dockerfile -t gcr.io/你的项目ID/gaokao-app .

# 推送镜像
docker push gcr.io/你的项目ID/gaokao-app
```

### Step 2：部署到 Cloud Run

```bash
gcloud run deploy gaokao-app \
  --image gcr.io/你的项目ID/gaokao-app \
  --region asia-east1 \
  --port 8000 \
  --allow-unauthenticated \
  --set-env-vars GAOKAO_DEV_MODE=true \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 1
```

### Step 3：获取访问 URL

部署完成后，gcloud 会输出一个 URL：`https://gaokao-app-xxxxx-de.a.run.app`

### 优势
- 按请求启动，无休眠等待（冷启动约 2-5 秒）
- 每月 200 万次免费请求
- 360,000 GB-秒/月免费计算资源

---

## 环境变量速查表

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `LLM_API_KEY` | 生产必填 | 无（dev 模式有默认值） | SiliconFlow API Key |
| `JWT_SECRET` | 生产必填 | 无（dev 模式有默认值） | JWT 签名密钥 |
| `GAOKAO_DEV_MODE` | 否 | `false` | 设为 `true` 可跳过上面两个 |
| `DATABASE_URL` | 否 | SQLite 本地文件 | MySQL 连接字符串 |
| `LLM_BASE_URL` | 否 | `https://api.siliconflow.cn/v1` | LLM API 地址 |
| `LLM_MODEL` | 否 | `Qwen/Qwen2.5-7B-Instruct` | LLM 模型名 |
| `SERVER_HOST` | 否 | `0.0.0.0` | 监听地址 |
| `SERVER_PORT` | 否 | `8000` | 监听端口 |
| `FRONTEND_DIR` | 否 | 自动检测 | 前端文件目录（Docker 用） |

---

## 常见问题

### Q: 部署后访问显示 502 Bad Gateway？
A: 服务正在启动中，等 1-2 分钟再试。检查 Render 日志是否有报错。

### Q: LLM 生成方案很慢或超时？
A: 免费版 SiliconFlow Qwen2.5-7B 响应较慢（10-30 秒）。Dockerfile 中已设置 120 秒超时。

### Q: 注册/登录后数据丢失？
A: 免费版无持久化磁盘，重新部署后 SQLite 数据会重置。测试期间可接受。

### Q: 如何获取 SiliconFlow API Key？
A: 访问 https://siliconflow.cn → 注册 → 控制台 → API 密钥 → 新建密钥。新用户送 2000 万 token 免费额度。

### Q: Render 免费版够用吗？
A: 测试完全够用。512MB 内存 + 单 worker 能处理几十个并发请求。正式上线建议升级到 Starter（$7/月）。
