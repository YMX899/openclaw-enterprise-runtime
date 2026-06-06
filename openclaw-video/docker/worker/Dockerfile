ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ARG PIP_INDEX_URL=
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOUYIN_CHONG_PYTHONPATH=/app/vendor

WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
COPY vendor/douyin_chong /app/vendor/douyin_chong
COPY docker/worker/entrypoint.sh /usr/local/bin/openclaw-worker-entrypoint.sh
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -i "$PIP_INDEX_URL" /app; \
    else \
        pip install --no-cache-dir /app; \
    fi

ENTRYPOINT ["sh", "/usr/local/bin/openclaw-worker-entrypoint.sh"]
CMD ["python", "-m", "openclaw_video.worker_main"]
