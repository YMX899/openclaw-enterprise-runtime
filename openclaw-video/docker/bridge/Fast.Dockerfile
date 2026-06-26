ARG BASE_IMAGE=openclaw-video-openclaw-bridge
FROM ${BASE_IMAGE}
USER root
WORKDIR /app
COPY pyproject.toml /app/
RUN rm -rf /app/src/openclaw_video/webdist
COPY src /app/src
COPY vendor/douyin_chong /app/vendor/douyin_chong
RUN pip install --no-cache-dir --no-deps /app \
    && python - <<'PY'
from pathlib import Path
import shutil
import openclaw_video

source = Path("/app/src/openclaw_video/webdist")
target = Path(openclaw_video.__file__).resolve().parent / "webdist"
if source.is_dir():
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
PY
