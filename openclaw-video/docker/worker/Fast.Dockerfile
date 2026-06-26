ARG BASE_IMAGE=openclaw-video-video-analysis-worker
FROM ${BASE_IMAGE}
USER root
WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
COPY vendor/douyin_chong /app/vendor/douyin_chong
RUN pip install --no-cache-dir --no-deps /app
ENTRYPOINT ["sh", "/usr/local/bin/openclaw-worker-entrypoint.sh"]
CMD ["python", "-m", "openclaw_video.worker_main"]
