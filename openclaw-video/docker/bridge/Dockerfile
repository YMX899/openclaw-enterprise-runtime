ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ARG PIP_INDEX_URL=
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
COPY docker/bridge/entrypoint.sh /usr/local/bin/openclaw-bridge-entrypoint.sh
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -i "$PIP_INDEX_URL" /app; \
    else \
        pip install --no-cache-dir /app; \
    fi

EXPOSE 3000
ENTRYPOINT ["sh", "/usr/local/bin/openclaw-bridge-entrypoint.sh"]
CMD ["uvicorn", "openclaw_video.bridge_app:app", "--host", "0.0.0.0", "--port", "3000"]
