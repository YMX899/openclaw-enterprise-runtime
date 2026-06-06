from pathlib import Path
from hashlib import sha256
import json
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.openclaw-video.yaml"
GATEWAY_DOCKERFILE = ROOT / "docker" / "openclaw-gateway" / "Dockerfile"
BRIDGE_DOCKERFILE = ROOT / "docker" / "bridge" / "Dockerfile"
WORKER_DOCKERFILE = ROOT / "docker" / "worker" / "Dockerfile"
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
        self.assertNotIn(":/knowledge/short-video:rw", compose)
        self.assertNotIn(":/knowledge/short-video\n", compose)

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
        self.assertIn("--auth token", dockerfile)
        self.assertNotIn("--token", dockerfile)
        self.assertIn("/run/secrets/openclaw_gateway_token", dockerfile)

    def test_sidecar_private_network_allows_required_egress(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("name: openclaw_video_internal", compose)
        self.assertNotIn("internal: true", compose)

    def test_dify_network_defaults_to_production_and_can_be_overridden_for_isolated_tests(self):
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertIn("name: ${DIFY_DOCKER_NETWORK:-docker_default}", compose)
        self.assertNotIn("name: docker_default\n", compose)

    def test_compose_render_checks_avoid_writing_interpolated_secret_values(self):
        gate_script = (ROOT.parents[0] / "scripts" / "verify_phase1_5_gates.sh").read_text(encoding="utf-8")
        helper_script = (ROOT.parents[0] / "scripts" / "verify_compose_render.sh").read_text(encoding="utf-8")

        for script in [gate_script, helper_script]:
            with self.subTest(script=script[:40]):
                self.assertIn("mktemp", script)
                self.assertIn("config --no-interpolate", script)
                self.assertIn("rm -f", script)

    def test_compose_render_checks_accept_compose_v5_normalized_port_shape(self):
        gate_script = (ROOT.parents[0] / "scripts" / "verify_phase1_5_gates.sh").read_text(encoding="utf-8")
        helper_script = (ROOT.parents[0] / "scripts" / "verify_compose_render.sh").read_text(encoding="utf-8")

        for script in [gate_script, helper_script]:
            with self.subTest(script=script[:40]):
                self.assertIn("host_ip: 127.0.0.1", script)
                self.assertIn('published: "18181"', script)
                self.assertIn("target: 3000", script)

    def test_worker_image_smoke_has_compose_v5_image_id_fallback(self):
        gate_script = (ROOT.parents[0] / "scripts" / "verify_phase1_5_gates.sh").read_text(encoding="utf-8")

        self.assertIn("compose -f \"$compose_file\" images -q video-analysis-worker", gate_script)
        self.assertIn("image inspect openclaw-video-video-analysis-worker:latest", gate_script)

    def test_phase1_5_compose_up_waits_for_health_and_cleans_volumes(self):
        gate_script = (ROOT.parents[0] / "scripts" / "verify_phase1_5_gates.sh").read_text(encoding="utf-8")

        self.assertIn("down --remove-orphans --volumes", gate_script)
        self.assertIn("for attempt in $(seq 1 30)", gate_script)
        self.assertIn("healthz: PASS attempt=", gate_script)
        self.assertIn("logs --tail=80 openclaw-bridge", gate_script)

    def test_worker_resource_and_filesystem_limits_are_declared(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        for required in [
            "WORKER_CONCURRENCY: \"1\"",
            "JOB_TIMEOUT_SECONDS: \"900\"",
            "MAX_DOWNLOAD_BYTES: \"536870912\"",
            "MAX_VIDEO_DURATION_SECONDS: \"60\"",
            "MAX_VIDEO_FRAMES: \"1200\"",
            "DOUYIN_CHONG_BIN: /usr/local/bin/openclaw-douyin-adapter",
            "DOUYIN_CHONG_ENV_FILE: /run/secrets/douyin_chong_env",
            "./secrets/douyin_chong.env:/run/secrets/douyin_chong_env:ro",
            "./vendor/douyin_chong:/app/vendor/douyin_chong:ro",
            "- worker-tmp:/tmp/openclaw-video",
            "read_only: true",
            "/tmp:size=1024m,nosuid,nodev",
            'cpus: "1.00"',
            "mem_limit: 1024M",
            "mem_reservation: 256M",
            "pids_limit: 128",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, compose)

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

    def test_base_images_default_to_official_and_can_be_overridden_for_isolated_hosts(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        bridge = BRIDGE_DOCKERFILE.read_text(encoding="utf-8")
        worker = WORKER_DOCKERFILE.read_text(encoding="utf-8")
        gateway = GATEWAY_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("ARG PYTHON_BASE_IMAGE=python:3.12-slim", bridge)
        self.assertIn("FROM ${PYTHON_BASE_IMAGE}", bridge)
        self.assertIn("ARG PIP_INDEX_URL=", bridge)
        self.assertIn('pip install --no-cache-dir -i "$PIP_INDEX_URL" /app', bridge)
        self.assertIn("ARG PYTHON_BASE_IMAGE=python:3.12-slim", worker)
        self.assertIn("FROM ${PYTHON_BASE_IMAGE}", worker)
        self.assertIn("ARG PIP_INDEX_URL=", worker)
        self.assertIn('pip install --no-cache-dir -i "$PIP_INDEX_URL" /app', worker)
        self.assertIn("ARG NODE_BASE_IMAGE=node:22.18-slim", gateway)
        self.assertIn("FROM ${NODE_BASE_IMAGE}", gateway)
        self.assertIn("ARG APT_DEBIAN_MIRROR=http://deb.debian.org/debian", gateway)
        self.assertIn("ARG APT_SECURITY_MIRROR=http://deb.debian.org/debian-security", gateway)
        self.assertIn("ARG NPM_CONFIG_REGISTRY=", gateway)
        self.assertIn("ENV OPENCLAW_RUNTIME_DIR=/opt/openclaw-runtime", gateway)
        self.assertIn("apt-get install -y --no-install-recommends ca-certificates git openssh-client", gateway)
        self.assertIn("COPY docker/openclaw-gateway/package*.json /opt/openclaw-runtime/", gateway)
        self.assertIn('npm config set registry "$NPM_CONFIG_REGISTRY"', gateway)
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
        self.assertIn("PYTHON_BASE_IMAGE: ${PYTHON_BASE_IMAGE:-python:3.12-slim}", compose)
        self.assertIn("PIP_INDEX_URL: ${PIP_INDEX_URL:-}", compose)
        self.assertIn("NODE_BASE_IMAGE: ${NODE_BASE_IMAGE:-node:22.18-slim}", compose)
        self.assertIn("APT_DEBIAN_MIRROR: ${APT_DEBIAN_MIRROR:-http://deb.debian.org/debian}", compose)
        self.assertIn(
            "APT_SECURITY_MIRROR: ${APT_SECURITY_MIRROR:-http://deb.debian.org/debian-security}",
            compose,
        )
        self.assertIn("NPM_CONFIG_REGISTRY: ${NPM_CONFIG_REGISTRY:-}", compose)
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
            "clients/douyin.py",
            "clients/resolver.py",
            "clients/tiktok.py",
            "config.py",
            "models.py",
            "README.md",
        }
        self.assertEqual(set(entries), expected_files)
        for relative, expected_digest in entries.items():
            path = vendor_root / Path(relative)
            try:
                data = subprocess.check_output(
                    ["git", "show", f"HEAD:openclaw-video/vendor/douyin_chong/{relative}"],
                    cwd=Path(__file__).resolve().parents[2],
                    stderr=subprocess.DEVNULL,
                )
            except (FileNotFoundError, subprocess.CalledProcessError):
                data = path.read_bytes()
            actual_digest = sha256(data).hexdigest()
            with self.subTest(relative=relative):
                self.assertEqual(actual_digest, expected_digest)


if __name__ == "__main__":
    unittest.main()
