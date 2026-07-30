# 高考志愿填报 App — 云服务器部署指南

> 本文档覆盖从零开始的完整部署流程。标注 **[你来做]** 的步骤需要你手动完成，
> 其余步骤我已帮你准备好配置文件。

---

## 📋 部署架构总览

```
用户浏览器
    ↓ HTTPS
Nginx (反向代理 + SSL + 限流)
    ↓ HTTP
FastAPI App (Docker 容器, 4 workers)
    ↓ HTTPS
SiliconFlow LLM API
    ↓ TCP
MySQL 8.0 (Docker 容器, 持久化存储)
```

---

## 一、云服务器选购 **[你来做]**

### 推荐配置（MVP 阶段）

| 项目 | 最低配置 | 建议配置 | 说明 |
|------|---------|---------|------|
| CPU | 2核 | 2核 | MVP 阶段流量不大 |
| 内存 | 2GB | 4GB | MySQL + FastAPI 共需 |
| 系统盘 | 40GB SSD | 50GB SSD | Docker 镜像 + 数据库 |
| 带宽 | 3Mbps | 5Mbps | 高考出分期可能需要更高 |
| 操作系统 | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS | 国内服务器选 CentOS 7.9 也可 |

### 云服务商选择

| 服务商 | 最低价格 | 特点 |
|--------|---------|------|
| 腾讯云轻量应用服务器 | ~50元/月 | 国内推荐，自带 DDOS 防护 |
| 阿里云 ECS | ~40元/月 | 生态完善，学生优惠 |
| AWS Lightsail | $5/月 | 海外用户访问更快 |

> **关键提醒**: 高考出分后 7-15 天是流量洪峰（80% 集中在此），届时需要临时升配。
> 建议选择支持弹性扩容的云服务商。

---

## 二、服务器基础环境 **[你来做]**

SSH 登录服务器后执行：

```bash
# 1. 更新系统
sudo apt update && sudo apt upgrade -y

# 2. 安装 Docker + Docker Compose
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable docker && sudo systemctl start docker

# 3. 安装常用工具
sudo apt install -y curl git vim

# 4. (可选) 安装 certbot 用于 Let's Encrypt SSL
sudo apt install -y certbot python3-certbot-nginx

# 5. 开放防火墙端口
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw allow 22/tcp    # SSH
sudo ufw enable
```

---

## 三、上传项目代码

### 方案 A：Git 克隆（推荐）

如果你把代码推到了 GitHub/Gitee：

```bash
# 在服务器上
cd /opt
git clone <你的仓库地址> gaokao-app
cd gaokao-app/gaokao-app
```

### 方案 B：SCP 直接上传

从本地电脑上传整个项目目录：

```bash
# 在本地电脑执行
scp -r D:/AI/WorkBuddy/WorkBuddy/WorkSpace/Program_Test/gaokao-app \
    root@<服务器IP>:/opt/gaokao-app
```

### 方案 C：使用 rsync（更高效，只同步增量）

```bash
# 在本地电脑执行
rsync -avz --exclude '__pycache__' --exclude '*.pyc' --exclude '*.db' --exclude 'logs/' \
    D:/AI/WorkBuddy/WorkBuddy/WorkSpace/Program_Test/gaokao-app \
    root@<服务器IP>:/opt/gaokao-app
```

---

## 四、配置环境变量 **[你来做]**

```bash
cd /opt/gaokao-app/gaokao-app/deploy

# 1. 复制环境变量模板
cp .env.example .env

# 2. 编辑 .env，填入真实值
vim .env
```

**必须修改的项**：

| 变量 | 说明 | 示例 |
|------|------|------|
| `LLM_API_KEY` | SiliconFlow API Key | `sk-xxxxxxxxx` |
| `JWT_SECRET` | JWT 签名密钥（强随机字符串） | 用 `openssl rand -hex 32` 生成 |
| `DATABASE_URL` | MySQL 连接串（使用 MySQL 时） | `mysql+pymysql://gaokao:密码@mysql:3306/gaokao_app` |

**生成强密钥**：

```bash
# 在服务器上运行
openssl rand -hex 32
# 输出类似: a1b2c3d4e5f6...64字符的随机字符串
# 将此值填入 .env 的 JWT_SECRET
```

---

## 五、MySQL 配置

### MVP 阶段：使用 SQLite（最简单）

如果 .env 中 `DATABASE_URL` 留空或注释掉，系统自动使用 SQLite。
此时在 docker-compose.yml 中**注释掉 mysql 服务**：

```yaml
# 注释掉 mysql 相关部分
# mysql:
#   ...
# depends_on 中也去掉 mysql
```

### 生产阶段：使用 MySQL

1. 在 .env 中设置：
   ```
   DATABASE_URL=mysql+pymysql://gaokao:你的密码@mysql:3306/gaokao_app
   MYSQL_PASSWORD=你的密码
   MYSQL_ROOT_PASSWORD=你的root密码
   ```

2. docker-compose.yml 保持 mysql 服务启用即可。

3. 数据库表会在首次启动时自动创建（`init_db()`）。

---

## 六、SSL / HTTPS 配置 **[你来做]**

### 方案 A：Let's Encrypt（免费，推荐）

需要先有一个域名并解析到服务器 IP。

```bash
# 1. 先不带 SSL 启动 nginx
# 修改 nginx.conf，临时只保留 HTTP server block
# 修改 docker-compose.yml，nginx 只映射 80 端口

# 2. 启动服务
docker compose up -d

# 3. 获取 SSL 证书
sudo certbot certonly --standalone -d 你的域名.com

# 4. 证书会保存在 /etc/letsencrypt/live/你的域名.com/
# 将证书链接到 deploy/ssl/
mkdir -p deploy/ssl
sudo cp /etc/letsencrypt/live/你的域名.com/fullchain.pem deploy/ssl/
sudo cp /etc/letsencrypt/live/你的域名.com/privkey.pem deploy/ssl/

# 5. 还原完整的 nginx.conf（包含 HTTPS）
# 重新启动
docker compose down && docker compose up -d

# 6. 设置自动续期
sudo certbot renew --dry-run  # 测试续期
# certbot 会自动添加 cron 任务续期
```

### 方案 B：腾讯云 SSL 证书服务

1. 在腾讯云控制台申请免费 SSL 证书
2. 下载 Nginx 格式证书
3. 解压后放到 `deploy/ssl/` 目录
4. 更新 nginx.conf 中 `ssl_certificate` 和 `ssl_certificate_key` 路径

### 方案 C：暂不用 HTTPS（仅用于测试）

修改 nginx.conf 只保留 HTTP server block，去掉 HTTPS 部分。
docker-compose.yml 中 nginx 只映射 80 端口。

> **⚠️ 生产环境务必启用 HTTPS！** 没有 HTTPS，用户密码和 JWT token 明文传输。

---

## 七、启动服务

```bash
cd /opt/gaokao-app/gaokao-app/deploy

# 构建并启动
docker compose up -d --build

# 查看状态
docker compose ps

# 查看日志
docker compose logs -f app        # 后端日志
docker compose logs -f nginx      # Nginx 日志
docker compose logs -f mysql      # MySQL 日志（如果启用）

# 停止服务
docker compose down

# 重启单个服务
docker compose restart app
```

---

## 八、验证部署

```bash
# 健康检查
curl http://localhost/api/health
# 应返回: {"code":0,"message":"success","data":{"status":"ok","version":"0.1.0"}}

# 测试前端页面
curl http://localhost/
# 应返回 HTML 页面内容

# 测试 LLM 生成（需要完整参数）
curl -X POST http://localhost/api/generate \
  -H "Content-Type: application/json" \
  -d '{"score":500,"province":"浙江","subjects":["物理","化学","生物"]}'
```

如果配置了域名和 HTTPS：

```bash
curl https://你的域名.com/api/health
```

---

## 九、日常运维

### 日志查看

```bash
# 实时查看后端日志
docker compose logs -f app

# 查看 Nginx 访问日志
docker compose exec nginx cat /var/log/nginx/gaokao_access.log

# 查看 MySQL 慢查询日志（如果启用）
docker compose exec mysql cat /var/log/mysql/mysql-slow.log
```

### 数据库备份

```bash
# SQLite 备份（如果使用 SQLite）
docker compose exec app cp /app/data/gaokao.db /app/data/gaokao_backup_$(date +%Y%m%d).db

# MySQL 备份（如果使用 MySQL）
docker compose exec mysql mysqldump -u gaokao -p gaokao_app > backup_$(date +%Y%m%d).sql
```

### 临时扩容（高考出分期）

```bash
# 增加后端 worker 数量
# 编辑 .env 中的 SERVER_WORKERS（如改为 8）

# 或者增加容器副本
docker compose up -d --scale app=3

# 在云服务商控制台临时升配 CPU/内存/带宽
```

### 更新代码

```bash
# Git 方式
cd /opt/gaokao-app/gaokao-app
git pull origin main

# 重新构建并启动
cd deploy
docker compose up -d --build
```

---

## 十、故障排查

| 问题 | 检查命令 | 解决方案 |
|------|---------|---------|
| 服务无法访问 | `docker compose ps` | 检查容器是否 running，重启 `docker compose restart app` |
| API 返回 500 | `docker compose logs app --tail 50` | 查看 LLM 调用是否失败，检查 API Key |
| 数据库连接失败 | `docker compose logs mysql --tail 20` | 检查 MySQL 是否就绪，DATABASE_URL 是否正确 |
| Nginx 502 | `docker compose ps app` | 后端未启动或端口不通，检查 app 健康状态 |
| SSL 证书过期 | `sudo certbot certificates` | 运行 `sudo certbot renew` |
| 端口被占用 | `sudo lsof -i :80` | 停止冲突服务或修改端口映射 |

---

## 十一、部署文件清单

我已帮你创建的文件：

```
gaokao-app/deploy/
├── .env.example        # 环境变量模板（需复制为 .env 并填写）
├── Dockerfile           # 后端 Docker 阜像构建文件
├── docker-compose.yml   # 一键部署编排
└── nginx.conf           # Nginx 反向代理 + SSL 配置

gaokao-app/.dockerignore # Docker 构建排除列表
```

代码修改：

| 文件 | 修改内容 |
|------|---------|
| `backend/config.py` | 环境变量化（LLM_API_KEY/JWT_SECRET/SERVER_* 不再有硬编码默认值） |
| `backend/main.py` | 去掉硬编码 API Key；添加启动环境检查；支持 FRONTEND_DIR 环境变量 |
| `backend/.gitignore` | 加入 .env 排除（防止密钥泄露） |

---

## 十二、你还需要做的事

### 必须做（否则服务无法启动）

1. **购买云服务器** — 选择配置、创建实例、获取 IP
2. **配置 .env** — 填入 LLM_API_KEY、JWT_SECRET、DATABASE_URL
3. **上传代码** — scp/rsync/git clone 到服务器
4. **域名 + HTTPS** — 购买域名、解析到服务器 IP、配置 SSL 证书

### 建议做（提升安全性和稳定性）

5. **MySQL 替代 SQLite** — 生产环境数据库持久化和并发性能更好
6. **自动备份** — 设置 cron 定时备份数据库和日志
7. **监控告警** — 腾讯云/阿里云自带监控，或安装 Prometheus + Grafana
8. **CI/CD** — 设置 GitHub Actions 自动构建部署

### 可以暂缓做（MVP 阶段不是必须）

9. CDN 加速（国内用户多时才有意义）
10. Redis 缓存层（降低 LLM API 调用频率）
11. 日志聚合（ELK/Loki — 流量大了才需要）
