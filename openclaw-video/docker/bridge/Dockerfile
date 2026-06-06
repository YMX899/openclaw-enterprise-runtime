ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
RUN pip install --no-cache-dir /app

USER 65532:65532
EXPOSE 3000
CMD ["uvicorn", "openclaw_video.bridge_app:app", "--host", "0.0.0.0", "--port", "3000"]
