ARG NODE_BASE_IMAGE=node:22.18-slim
FROM ${NODE_BASE_IMAGE}

ARG OPENCLAW_VERSION=2026.3.13
ARG APT_DEBIAN_MIRROR=http://deb.debian.org/debian
ARG APT_SECURITY_MIRROR=http://deb.debian.org/debian-security
ARG NPM_CONFIG_REGISTRY=
ARG PIP_INDEX_URL=
ENV DEBIAN_FRONTEND=noninteractive \
    OPENCLAW_RUNTIME_DIR=/opt/openclaw-runtime \
    DOUYIN_CHONG_PYTHONPATH=/app/vendor
USER root
RUN set -eux; \
    find /etc/apt -type f \( -name "*.list" -o -name "*.sources" \) -print0 \
        | xargs -0 sed -i \
            -e "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
            -e "s|http://deb.debian.org/debian|${APT_DEBIAN_MIRROR}|g"; \
    apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=60 -o Acquire::https::Timeout=60 update \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=60 -o Acquire::https::Timeout=60 install -y --no-install-recommends ca-certificates git openssh-client python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
COPY docker/openclaw-gateway/package*.json /opt/openclaw-runtime/
COPY docker/openclaw-gateway/entrypoint.sh /usr/local/bin/openclaw-gateway-entrypoint.sh
COPY pyproject.toml /app/
COPY src /app/src
COPY vendor/douyin_chong /app/vendor/douyin_chong
RUN if [ -n "$NPM_CONFIG_REGISTRY" ]; then \
        npm config set registry "$NPM_CONFIG_REGISTRY"; \
    fi \
    && npm config set fetch-retries 3 \
    && npm config set fetch-timeout 60000 \
    && npm config set fetch-retry-maxtimeout 60000 \
    && git config --global url."https://github.com/".insteadOf ssh://git@github.com/ \
    && cd "$OPENCLAW_RUNTIME_DIR" \
    && npm ci --omit=optional --ignore-scripts --no-audit --no-fund \
    && ./node_modules/.bin/openclaw --version \
    && if [ -n "$PIP_INDEX_URL" ]; then \
        python3 -m pip install --break-system-packages --no-cache-dir --timeout 60 --retries 3 -i "$PIP_INDEX_URL" /app; \
    else \
        python3 -m pip install --break-system-packages --no-cache-dir --timeout 60 --retries 3 /app; \
    fi \
    && openclaw-agent-video-analyze --help >/dev/null

ENV OPENCLAW_STATE_DIR=/var/lib/openclaw \
    HOME=/var/lib/openclaw \
    XDG_CONFIG_HOME=/var/lib/openclaw/.config \
    XDG_CACHE_HOME=/var/lib/openclaw/.cache \
    XDG_DATA_HOME=/var/lib/openclaw/.local/share \
    OPENCLAW_CONFIG_PATH=/etc/openclaw/config.yaml \
    PATH=/opt/openclaw-runtime/node_modules/.bin:$PATH

RUN mkdir -p /var/lib/openclaw /etc/openclaw \
    && chown -R node:node /var/lib/openclaw /etc/openclaw

EXPOSE 18789
ENTRYPOINT ["sh", "/usr/local/bin/openclaw-gateway-entrypoint.sh"]
CMD ["openclaw", "gateway", "run", "--allow-unconfigured", "--bind", "lan", "--port", "18789", "--auth", "token"]
