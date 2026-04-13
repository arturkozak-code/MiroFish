# syntax=docker/dockerfile:1.7

# =========================================================
# Stage 1: 构建前端静态资源（Vite 生产构建）
# =========================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# 安装前端依赖（利用缓存层）
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm ci --prefix frontend

# 构建前端
COPY frontend/ ./frontend/
COPY locales/ ./locales/
RUN npm --prefix frontend run build

# =========================================================
# Stage 2: 生产运行时（Python + Flask + Gunicorn）
# =========================================================
FROM python:3.11-slim AS runtime

# 从 uv 官方镜像复制 uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

# 先复制依赖描述文件以利用缓存
COPY backend/pyproject.toml ./backend/
COPY backend/uv.lock ./backend/

# 安装后端依赖（不使用 --frozen，因为新增了 gunicorn 依赖；
# 生产构建时允许 uv 解析最新兼容的 lock）
RUN cd backend && uv sync --no-dev

# 复制后端源码
COPY backend/ ./backend/

# 从 frontend-builder 拷贝构建好的前端静态资源
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# 生产环境配置
ENV FLASK_DEBUG=False \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DIST_DIR=/app/frontend/dist \
    PORT=8080

# Railway/云平台会通过 $PORT 注入端口；EXPOSE 仅用于文档
EXPOSE 8080

WORKDIR /app/backend

# 使用 gunicorn 作为生产 WSGI 服务器
# 注意：shell 形式让 $PORT 被解析；worker 数量保持较小，因后端内存占用可能较高
CMD sh -c 'uv run gunicorn "app:create_app()" \
      --bind 0.0.0.0:${PORT:-8080} \
      --workers ${WEB_CONCURRENCY:-2} \
      --timeout ${GUNICORN_TIMEOUT:-120} \
      --access-logfile - \
      --error-logfile -'
