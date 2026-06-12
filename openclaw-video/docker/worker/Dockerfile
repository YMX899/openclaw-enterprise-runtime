ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ARG APT_DEBIAN_MIRROR=http://deb.debian.org/debian
ARG APT_SECURITY_MIRROR=http://deb.debian.org/debian-security
ARG PIP_INDEX_URL=
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOUYIN_CHONG_PYTHONPATH=/app/vendor

WORKDIR /app
RUN set -eux; \
    sed -i "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g; s|http://deb.debian.org/debian|${APT_DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /app/
COPY src /app/src
COPY vendor/douyin_chong /app/vendor/douyin_chong
COPY docker/worker/entrypoint.sh /usr/local/bin/openclaw-worker-entrypoint.sh
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir --timeout 60 --retries 3 -i "$PIP_INDEX_URL" /app; \
    else \
        pip install --no-cache-dir --timeout 60 --retries 3 /app; \
    fi

ENTRYPOINT ["sh", "/usr/local/bin/openclaw-worker-entrypoint.sh"]
CMD ["python", "-m", "openclaw_video.worker_main"]
