FROM python:3.11-slim

# 绿联对比 digest：每次发布改此版本号再 push，即可出现「可更新」
ARG APP_VERSION=2026.08.20.8
LABEL org.opencontainers.image.title="GoFly" \
      org.opencontainers.image.description="国内机票价格监控" \
      org.opencontainers.image.version="${APP_VERSION}"

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GOFLY_CONFIG=/app/config.yaml \
    GOFLY_HOST=0.0.0.0 \
    GOFLY_PORT=8787 \
    TZ=Asia/Shanghai

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config.example.yaml ./config.example.yaml
COPY VERSION ./VERSION

# 无挂载 config.yaml 时用示例配置启动（host 已为 0.0.0.0）
RUN cp config.example.yaml config.yaml

EXPOSE 8787

CMD ["python", "-m", "app.main"]
