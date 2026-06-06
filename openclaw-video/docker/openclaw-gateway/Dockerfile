ARG NODE_BASE_IMAGE=node:22.18-slim
FROM ${NODE_BASE_IMAGE}

ARG OPENCLAW_VERSION=2026.3.13
ARG APT_DEBIAN_MIRROR=http://deb.debian.org/debian
ARG APT_SECURITY_MIRROR=http://deb.debian.org/debian-security
ARG NPM_CONFIG_REGISTRY=
USER root
RUN set -eux; \
    find /etc/apt -type f \( -name "*.list" -o -name "*.sources" \) -print0 \
        | xargs -0 sed -i \
            -e "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
            -e "s|http://deb.debian.org/debian|${APT_DEBIAN_MIRROR}|g"; \
    apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
RUN if [ -n "$NPM_CONFIG_REGISTRY" ]; then \
        npm config set registry "$NPM_CONFIG_REGISTRY"; \
    fi \
    && npm install -g "openclaw@${OPENCLAW_VERSION}" --ignore-scripts \
    && openclaw --version

ENV OPENCLAW_STATE_DIR=/var/lib/openclaw \
    OPENCLAW_CONFIG_PATH=/etc/openclaw/config.yaml

RUN mkdir -p /var/lib/openclaw /etc/openclaw \
    && chown -R node:node /var/lib/openclaw /etc/openclaw

USER node
EXPOSE 18789
CMD ["sh", "-lc", "OPENCLAW_GATEWAY_TOKEN=\"$(cat /run/secrets/openclaw_gateway_token)\" exec openclaw gateway run --bind custom --port 18789 --auth token"]
