FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOUYIN_CHONG_PYTHONPATH=/app/vendor

WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
COPY vendor/douyin_chong /app/vendor/douyin_chong
RUN pip install --no-cache-dir /app

USER 65532:65532
CMD ["python", "-m", "openclaw_video.worker_main"]
