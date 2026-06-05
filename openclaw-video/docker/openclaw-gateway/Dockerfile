FROM node:22.18-slim

ARG OPENCLAW_VERSION=2026.3.13
RUN npm install -g "openclaw@${OPENCLAW_VERSION}" --ignore-scripts \
    && openclaw --version

ENV OPENCLAW_STATE_DIR=/var/lib/openclaw \
    OPENCLAW_CONFIG_PATH=/etc/openclaw/config.yaml

RUN mkdir -p /var/lib/openclaw /etc/openclaw \
    && chown -R node:node /var/lib/openclaw /etc/openclaw

USER node
EXPOSE 18789
CMD ["sh", "-lc", "openclaw gateway run --bind custom --port 18789 --auth token --token \"$OPENCLAW_GATEWAY_TOKEN\""]

