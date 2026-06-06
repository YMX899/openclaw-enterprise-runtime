ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ARG PIP_INDEX_URL=
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -i "$PIP_INDEX_URL" /app; \
    else \
        pip install --no-cache-dir /app; \
    fi

USER 65532:65532
EXPOSE 3000
CMD ["uvicorn", "openclaw_video.bridge_app:app", "--host", "0.0.0.0", "--port", "3000"]
