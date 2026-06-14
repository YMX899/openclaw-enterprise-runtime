from pathlib import Path
from hashlib import sha256
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.openclaw-video.yaml"
GATEWAY_DOCKERFILE = ROOT / "docker" / "openclaw-gateway" / "Dockerfile"
BRIDGE_DOCKERFILE = ROOT / "docker" / "bridge" / "Dockerfile"
WORKER_DOCKERFILE = ROOT / "docker" / "worker" / "Dockerfile"
BRIDGE_ENTRYPOINT = ROOT / "docker" / "bridge" / "entrypoint.sh"
GATEWAY_ENTRYPOINT = ROOT / "docker" / "openclaw-gateway" / "entrypoint.sh"
GATEWAY_CONFIG = ROOT / "openclaw" / "config" / "config.yaml"
WORKER_ENTRYPOINT = ROOT / "docker" / "worker" / "entrypoint.sh"
DOCKERIGNORE = ROOT / ".dockerignore"
VENDOR_GITIGNORE = ROOT / "vendor" / "douyin_chong" / ".gitignore"
VENDOR_HASHES = ROOT / "vendor" / "douyin_chong" / "SOURCE_SHA256SUMS"


class ComposeContractTests(unittest.TestCase):
    def test_knowledge_base_is_mounted_read_only(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        expected_mount = "../artifacts/knowledge-base-short-video/2026.06.06:/knowledge/short-video:ro"
        self.assertIn(expected_mount, compose)
        self.assertIn("KNOWLEDGE_BASE_DIR: /knowledge/short-video", compose)
        self.assertIn("KNOWLEDGE_BASE_VERSION_FILE: /knowledge/short-video/VERSION", compose)
        self.assertIn('OPENCLAW_VERSION: "2026.3.13"', compose)
        self.assertNotIn(":/knowledge/short-video:rw", compose)
        self.assertNotIn(":/knowledge/short-video\n", compose)

    def test_phase4_control_environment_is_declared_for_controlled_trials(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        bridge_block = compose.split("\n  bridge-postgres:", 1)[0]
        for required in [
            "OPENCLAW_VIDEO_RELEASE: ${OPENCLAW_VIDEO_RELEASE:-unknown}",
            "OPENCLAW_TENANT_ALLOWLIST_HASHES: ${OPENCLAW_TENANT_ALLOWLIST_HASHES:-}",
            "OPENCLAW_ACCOUNT_ALLOWLIST_HASHES: ${OPENCLAW_ACCOUNT_ALLOWLIST_HASHES:-}",
            "OPENCLAW_USER_ACTIVE_JOB_LIMIT: ${OPENCLAW_USER_ACTIVE_JOB_LIMIT:-2}",
            "OPENCLAW_USER_RATE_LIMIT_PER_MINUTE: ${OPENCLAW_USER_RATE_LIMIT_PER_MINUTE:-12}",
            "OPENCLAW_DATA_RETENTION_DAYS: ${OPENCLAW_DATA_RETENTION_DAYS:-30}",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, bridge_block)

    def test_sidecar_forbidden_public_surfaces_are_not_declared(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        for forbidden in [
            "0.0.0.0:18789",
            "0.0.0.0:5432",
            "/var/run/docker.sock",
            "OPENCLAW_GATEWAY_URL: http://",
            "OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN",
            "OPENCLAW_GATEWAY_TOKEN:",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, compose)

    def test_bridge_gateway_contract_uses_ws_and_read_only_secret_files(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        for required in [
            "OPENCLAW_GATEWAY_URL: ws://openclaw-gateway:18789",
            "OPENCLAW_GATEWAY_TOKEN_FILE: /run/secrets/openclaw_gateway_token",
            "OPENCLAW_GATEWAY_DEVICE_KEY_FILE: /run/secrets/openclaw_bridge_device_key.pem",
            "./secrets/openclaw_gateway_token:/run/secrets/openclaw_gateway_token:ro",
            "./secrets/openclaw_bridge_device_key.pem:/run/secrets/openclaw_bridge_device_key.pem:ro",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, compose)

    def test_gateway_entrypoint_does_not_expand_token_into_process_args(self):
        dockerfile = GATEWAY_DOCKERFILE.read_text(encoding="utf-8")
        entrypoint = GATEWAY_ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn('"--auth", "token"', dockerfile)
        self.assertIn('"--allow-unconfigured"', dockerfile)
        self.assertIn('"--bind", "lan"', dockerfile)
        self.assertNotIn('"--bind", "custom"', dockerfile)
        self.assertNotIn('"--force"', dockerfile)
        self.assertNotIn('"--reset"', dockerfile)
        self.assertNotIn("--token", dockerfile)
        self.assertIn("/run/secrets/openclaw_gateway_token", entrypoint)
        self.assertIn('OPENCLAW_GATEWAY_TOKEN="$(cat "$TOKEN_FILE")"', entrypoint)
        self.assertIn('DOUYIN_CHONG_ENV_FILE="${DOUYIN_CHONG_ENV_FILE:-/run/secrets/douyin_chong_env}"', entrypoint)
        self.assertIn('read_dotenv_key ARK_API_KEY "$DOUYIN_CHONG_ENV_FILE"', entrypoint)
        self.assertIn("VOLCANO_ENGINE_API_KEY", entrypoint)
        self.assertIn('OPENCLAW_HOME="${OPENCLAW_HOME:-${OPENCLAW_STATE_DIR:-/var/lib/openclaw}}"', entrypoint)
        self.assertIn('HOME="$OPENCLAW_HOME"', entrypoint)
        self.assertIn("refusing to use unsafe OpenClaw home directory", entrypoint)
        self.assertIn('mkdir -p "$HOME/.openclaw" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME"', entrypoint)
        self.assertIn('chown -R "$APP_UID:$APP_GID" "$HOME"', entrypoint)
        self.assertIn('DOUYIN_CHONG_PYTHONPATH="${DOUYIN_CHONG_PYTHONPATH:-/app/vendor}"', entrypoint)
        self.assertIn('MAX_DOWNLOAD_BYTES="${MAX_DOWNLOAD_BYTES:-524288000}"', entrypoint)
        self.assertIn('MAX_VIDEO_DURATION_SECONDS="${MAX_VIDEO_DURATION_SECONDS:-0}"', entrypoint)
        self.assertIn('MAX_VIDEO_FRAMES="${MAX_VIDEO_FRAMES:-0}"', entrypoint)
        self.assertIn("HOME=/var/lib/openclaw", dockerfile)
        self.assertIn("XDG_CONFIG_HOME=/var/lib/openclaw/.config", dockerfile)
        self.assertIn('exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"', entrypoint)
        self.assertNotIn('HOME="${HOME:-/home/node}"', entrypoint)
        self.assertNotIn("exec openclaw", entrypoint)
        self.assertNotIn("--token", entrypoint)

    def test_gateway_config_is_private_backend_only(self):
        config = GATEWAY_CONFIG.read_text(encoding="utf-8")

        self.assertIn('mode: "local"', config)
        self.assertIn('bind: "lan"', config)
        self.assertIn("port: 18789", config)
        self.assertIn('mode: "token"', config)
        self.assertIn("controlUi:", config)
        self.assertIn("enabled: false", config)
        self.assertIn("agents:", config)
        self.assertIn('primary: "volcengine-plan/ark-code-latest"', config)
        self.assertIn("models:", config)
        self.assertIn("params:", config)
        self.assertIn("maxTokens: 32768", config)
        self.assertNotIn("allowedOrigins: [\"*\"]", config)
        self.assertNotIn("dangerouslyAllowHostHeaderOriginFallback", config)
        self.assertNotIn("dangerouslyDisableDeviceAuth", config)
        self.assertNotIn("allowInsecureAuth", config)
        self.assertNotIn("token:", config)
        self.assertNotIn("password:", config)

    def test_service_entrypoints_stage_secrets_then_drop_privileges(self):
        bridge = BRIDGE_ENTRYPOINT.read_text(encoding="utf-8")
        worker = WORKER_ENTRYPOINT.read_text(encoding="utf-8")
        gateway = GATEWAY_ENTRYPOINT.read_text(encoding="utf-8")

        for entrypoint in [bridge, worker]:
            with self.subTest(entrypoint=entrypoint[:32]):
                self.assertIn('APP_UID="${APP_UID:-65532}"', entrypoint)
                self.assertIn("stage_secret", entrypoint)
                self.assertIn('chmod 0700 "$SECRET_TMP_DIR"', entrypoint)
                self.assertIn('chmod 0400 "$target_path"', entrypoint)
                self.assertIn('exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"', entrypoint)

        self.assertIn('APP_UID="${APP_UID:-1000}"', gateway)
        self.assertIn('exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"', gateway)
        self.assertIn('SKIP_SECRET_STAGING:-0', worker)
        self.assertIn('mkdir -p "$BRIDGE_UPLOAD_DIR"', bridge)
        self.assertIn('chown "$APP_UID:$APP_GID" "$BRIDGE_UPLOAD_DIR"', bridge)
        self.assertIn('chmod 0750 "$BRIDGE_UPLOAD_DIR"', bridge)
        self.assertIn("ENTRYPOINT", BRIDGE_DOCKERFILE.read_text(encoding="utf-8"))
        self.assertIn("ENTRYPOINT", WORKER_DOCKERFILE.read_text(encoding="utf-8"))
        self.assertIn("ENTRYPOINT", GATEWAY_DOCKERFILE.read_text(encoding="utf-8"))
        self.assertNotIn("SKIP_SECRET_STAGING", COMPOSE.read_text(encoding="utf-8"))

    def test_sidecar_private_network_allows_required_egress(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("name: openclaw_video_internal", compose)
        self.assertNotIn("internal: true", compose)

    def test_bridge_postgres_uses_root_available_postgres_15_image(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        postgres_block = compose.split("\n  bridge-postgres:", 1)[1].split("\n  openclaw-gateway:", 1)[0]

        self.assertIn("image: postgres:15-alpine", postgres_block)
        self.assertNotIn("image: postgres:16-alpine", postgres_block)

    def test_dify_network_defaults_to_production_and_can_be_overridden_for_isolated_tests(self):
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertIn("name: ${DIFY_DOCKER_NETWORK:-docker_default}", compose)
        self.assertNotIn("name: docker_default\n", compose)

    def test_compose_render_checks_avoid_writing_interpolated_secret_values(self):
        helper_script = (ROOT.parents[0] / "scripts" / "verify_compose_render.sh").read_text(encoding="utf-8")

        self.assertIn("mktemp", helper_script)
        self.assertIn("config --no-interpolate", helper_script)
        self.assertIn("rm -f", helper_script)

    def test_compose_render_checks_accept_compose_v5_normalized_port_shape(self):
        helper_script = (ROOT.parents[0] / "scripts" / "verify_compose_render.sh").read_text(encoding="utf-8")

        self.assertIn("host_ip: 127.0.0.1", helper_script)
        self.assertIn('published: "18181"', helper_script)
        self.assertIn("target: 3000", helper_script)

    def test_compose_render_rejects_current_forbidden_public_and_secret_surfaces(self):
        helper_script = (ROOT.parents[0] / "scripts" / "verify_compose_render.sh").read_text(encoding="utf-8")
        for forbidden in [
            "0\\.0\\.0\\.0:18789",
            "0\\.0\\.0\\.0:5432",
            "/var/run/docker\\.sock",
            "internal: true",
            "--token",
            "sk-[[:alnum:]_-]+",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertIn(forbidden, helper_script)

    def test_worker_resource_and_filesystem_limits_are_declared(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        for required in [
            "WORKER_CONCURRENCY: \"1\"",
            "JOB_TIMEOUT_SECONDS: \"900\"",
            "VIDEO_ANALYSIS_INPUT_MODE: files_api",
            "ARK_RESPONSES_BASE_URL: ${ARK_RESPONSES_BASE_URL:-https://ark.cn-beijing.volces.com/api/v3}",
            "ARK_RESPONSES_MODEL: ${ARK_RESPONSES_MODEL:-doubao-seed-2-0-lite-260428}",
            "FILES_API_TIMEOUT_SECONDS: ${FILES_API_TIMEOUT_SECONDS:-300}",
            "MAX_DOWNLOAD_BYTES: \"524288000\"",
            "MAX_VIDEO_DURATION_SECONDS: \"0\"",
            "MAX_VIDEO_FRAMES: \"0\"",
            "DOUYIN_CHONG_BIN: /usr/local/bin/openclaw-douyin-adapter",
            "DOUYIN_CHONG_ENV_FILE: /run/secrets/douyin_chong_env",
            "BRIDGE_UPLOAD_DIR: /data/uploads",
            "MAX_UPLOAD_BYTES: \"524288000\"",
            "./secrets/douyin_chong.env:/run/secrets/douyin_chong_env:ro",
            "./vendor/douyin_chong:/app/vendor/douyin_chong:ro",
            "- worker-tmp:/tmp/openclaw-video",
            "- uploaded-videos:/data/uploads:ro",
            "read_only: true",
            "/tmp:size=1024m,nosuid,nodev",
            'cpus: "1.00"',
            "mem_limit: 1024M",
            "mem_reservation: 256M",
            "pids_limit: 128",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, compose)

    def test_upload_volume_is_bridge_writable_and_worker_read_only(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        bridge_block = compose.split("  bridge-postgres:", 1)[0]
        worker_block = compose.split("  video-analysis-worker:", 1)[1].split("\nvolumes:", 1)[0]

        self.assertIn("- uploaded-videos:/data/uploads", bridge_block)
        self.assertNotIn("- uploaded-videos:/data/uploads:ro", bridge_block)
        self.assertIn("- uploaded-videos:/data/uploads:ro", worker_block)
        self.assertIn("uploaded-videos:", compose)

    def test_only_bridge_joins_dify_network(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        bridge_block = compose.split("  bridge-postgres:", 1)[0]
        gateway_block = compose.split("  openclaw-gateway:", 1)[1].split("  video-analysis-worker:", 1)[0]
        worker_block = compose.split("  video-analysis-worker:", 1)[1].split("volumes:", 1)[0]
        postgres_block = compose.split("  bridge-postgres:", 1)[1].split("  openclaw-gateway:", 1)[0]
        self.assertIn("- dify-default", bridge_block)
        self.assertNotIn("- dify-default", gateway_block)
        self.assertNotIn("- dify-default", worker_block)
        self.assertNotIn("- dify-default", postgres_block)

    def test_douyin_tool_secrets_are_file_mounted_not_inline(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("DOUYIN_CHONG_ENV_FILE: /run/secrets/douyin_chong_env", compose)
        self.assertIn("./secrets/douyin_chong.env:/run/secrets/douyin_chong_env:ro", compose)
        self.assertNotIn("ARK_API_KEY:", compose)
        self.assertNotIn("MEDIAKIT_API_KEY:", compose)

    def test_worker_image_uses_adapter_and_vendor_source_slot(self):
        dockerfile = WORKER_DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("DOUYIN_CHONG_PYTHONPATH=/app/vendor", dockerfile)
        self.assertIn("COPY vendor/douyin_chong /app/vendor/douyin_chong", dockerfile)
        self.assertIn("openclaw-douyin-adapter", (ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_bridge_image_includes_vendor_resolver_for_link_read_checks(self):
        dockerfile = BRIDGE_DOCKERFILE.read_text(encoding="utf-8")
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertIn("COPY vendor/douyin_chong /app/vendor/douyin_chong", dockerfile)
        self.assertIn('MAX_DOWNLOAD_BYTES: "524288000"', compose)
        self.assertIn('MAX_VIDEO_DURATION_SECONDS: "0"', compose)

    def test_base_images_default_to_official_and_can_be_overridden_for_isolated_hosts(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        bridge = BRIDGE_DOCKERFILE.read_text(encoding="utf-8")
        worker = WORKER_DOCKERFILE.read_text(encoding="utf-8")
        gateway = GATEWAY_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("ARG PYTHON_BASE_IMAGE=python:3.12-slim", bridge)
        self.assertIn("FROM ${PYTHON_BASE_IMAGE}", bridge)
        self.assertIn("ARG PIP_INDEX_URL=", bridge)
        self.assertIn('pip install --no-cache-dir --timeout 60 --retries 3 -i "$PIP_INDEX_URL" /app', bridge)
        self.assertIn("ARG PYTHON_BASE_IMAGE=python:3.12-slim", worker)
        self.assertIn("FROM ${PYTHON_BASE_IMAGE}", worker)
        self.assertIn("ARG PIP_INDEX_URL=", worker)
        self.assertIn('pip install --no-cache-dir --timeout 60 --retries 3 -i "$PIP_INDEX_URL" /app', worker)
        self.assertIn("ARG NODE_BASE_IMAGE=node:22.18-slim", gateway)
        self.assertIn("FROM ${NODE_BASE_IMAGE}", gateway)
        self.assertIn("ARG APT_DEBIAN_MIRROR=http://deb.debian.org/debian", gateway)
        self.assertIn("ARG APT_SECURITY_MIRROR=http://deb.debian.org/debian-security", gateway)
        self.assertIn("ARG NPM_CONFIG_REGISTRY=", gateway)
        self.assertIn("OPENCLAW_RUNTIME_DIR=/opt/openclaw-runtime", gateway)
        self.assertIn("DEBIAN_FRONTEND=noninteractive", gateway)
        self.assertIn("Acquire::Retries=3", gateway)
        self.assertIn("Acquire::http::Timeout=60", gateway)
        self.assertIn("install -y --no-install-recommends ca-certificates git openssh-client", gateway)
        self.assertIn("COPY docker/openclaw-gateway/package*.json /opt/openclaw-runtime/", gateway)
        self.assertIn('npm config set registry "$NPM_CONFIG_REGISTRY"', gateway)
        self.assertIn("npm config set fetch-retries 3", gateway)
        self.assertIn("npm config set fetch-timeout 60000", gateway)
        self.assertIn('git config --global url."https://github.com/".insteadOf ssh://git@github.com/', gateway)
        self.assertIn("npm ci --omit=optional --ignore-scripts --no-audit --no-fund", gateway)
        self.assertIn("./node_modules/.bin/openclaw --version", gateway)
        self.assertIn("PATH=/opt/openclaw-runtime/node_modules/.bin:$PATH", gateway)
        self.assertNotIn("npm install -g", gateway)
        self.assertIn("rm -rf /var/lib/apt/lists/*", gateway)

        package_json = json.loads((ROOT / "docker" / "openclaw-gateway" / "package.json").read_text(encoding="utf-8"))
        package_lock = json.loads(
            (ROOT / "docker" / "openclaw-gateway" / "package-lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(package_json["dependencies"]["openclaw"], "2026.3.13")
        self.assertEqual(package_json["overrides"]["@whiskeysockets/baileys"]["libsignal"], "6.0.0")
        self.assertEqual(package_lock["packages"]["node_modules/openclaw"]["version"], "2026.3.13")
        libsignal_lock = package_lock["packages"]["node_modules/libsignal"]
        self.assertEqual(libsignal_lock["version"], "6.0.0")
        self.assertIn("/libsignal-6.0.0.tgz", libsignal_lock["resolved"])
        self.assertNotIn("github.com/whiskeysockets/libsignal-node", libsignal_lock["resolved"])
        self.assertNotIn("github.com/whiskeysockets/libsignal-node", json.dumps(package_lock))
        self.assertIn("PYTHON_BASE_IMAGE: ${PYTHON_BASE_IMAGE:-python:3.12-slim}", compose)
        self.assertIn("PIP_INDEX_URL: ${PIP_INDEX_URL:-}", compose)
        self.assertIn("pip install --no-cache-dir --timeout 60 --retries 3", bridge)
        self.assertIn("pip install --no-cache-dir --timeout 60 --retries 3", worker)
        self.assertIn("NODE_BASE_IMAGE: ${NODE_BASE_IMAGE:-node:22.18-slim}", compose)
        self.assertIn("APT_DEBIAN_MIRROR: ${APT_DEBIAN_MIRROR:-http://deb.debian.org/debian}", compose)
        self.assertIn(
            "APT_SECURITY_MIRROR: ${APT_SECURITY_MIRROR:-http://deb.debian.org/debian-security}",
            compose,
        )
        self.assertIn("NPM_CONFIG_REGISTRY: ${NPM_CONFIG_REGISTRY:-}", compose)
        self.assertIn("PIP_INDEX_URL: ${PIP_INDEX_URL:-}", compose)
        self.assertIn("install -y --no-install-recommends ca-certificates git openssh-client python3 python3-pip", gateway)
        self.assertIn("COPY pyproject.toml /app/", gateway)
        self.assertIn("COPY src /app/src", gateway)
        self.assertIn("COPY vendor/douyin_chong /app/vendor/douyin_chong", gateway)
        self.assertIn("DOUYIN_CHONG_PYTHONPATH=/app/vendor", gateway)
        self.assertIn("openclaw-agent-video-analyze --help", gateway)
        self.assertIn("openclaw-agent-video-analyze", (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertNotIn("public.ecr.aws", compose)
        self.assertNotIn("pypi.tuna.tsinghua.edu.cn", compose)

    def test_vendor_slot_keeps_secrets_and_runtime_outputs_out(self):
        dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")
        vendor_gitignore = VENDOR_GITIGNORE.read_text(encoding="utf-8")
        for forbidden in [
            "vendor/douyin_chong/.env",
            "vendor/douyin_chong/.env.*",
            "vendor/douyin_chong/*storage*",
            "vendor/douyin_chong/**/*.log",
            "vendor/douyin_chong/**/__pycache__",
            "vendor/douyin_chong/**/*.pyc",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertIn(forbidden, dockerignore)
        self.assertIn(".env.*", vendor_gitignore)
        self.assertIn("*storage*", vendor_gitignore)
        self.assertIn("**/__pycache__/", vendor_gitignore)
        self.assertIn("cover_exports/", vendor_gitignore)
        self.assertTrue((ROOT / "vendor" / "douyin_chong" / "config.py").is_file())
        self.assertTrue((ROOT / "vendor" / "douyin_chong" / "clients" / "ark_video.py").is_file())
        self.assertFalse((ROOT / "vendor" / "douyin_chong" / "douyin_login_state.py").exists())
        self.assertFalse((ROOT / "vendor" / "douyin_chong" / "profile_batch_fashion.py").exists())

    def test_vendor_source_hash_manifest_matches_current_files(self):
        vendor_root = ROOT / "vendor" / "douyin_chong"
        entries = {}
        for raw_line in VENDOR_HASHES.read_text(encoding="utf-8").splitlines():
            digest, relative = raw_line.split("  ", 1)
            entries[relative] = digest
        expected_files = {
            "__init__.py",
            "clients/__init__.py",
            "clients/ark_video.py",
            "clients/bilibili.py",
            "clients/douyin.py",
            "clients/resolver.py",
            "clients/tiktok.py",
            "clients/xiaohongshu.py",
            "config.py",
            "models.py",
            "README.md",
        }
        self.assertEqual(set(entries), expected_files)
        for relative, expected_digest in entries.items():
            path = vendor_root / Path(relative)
            data = path.read_bytes()
            actual_digest = sha256(data).hexdigest()
            with self.subTest(relative=relative):
                self.assertEqual(actual_digest, expected_digest)


if __name__ == "__main__":
    unittest.main()
