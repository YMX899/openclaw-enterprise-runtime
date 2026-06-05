# douyin_chong Artifact Manifest

Status: missing. This file is a production gate, not a deployment approval.

The real video-analysis artifact has not been found locally or on the server.

## Required Evidence Before Phase 2

- source repository, archive, or image.
- commit hash or artifact version.
- SHA256 or image digest.
- license and production-use permission.
- runtime language and version.
- dependency lockfile.
- exact command entrypoint.
- required environment variables.
- whether cookies, tokens, proxy credentials, or browser state are required.
- expected network destinations.
- input schema.
- output JSON schema.
- error code contract.
- average runtime per video.
- maximum runtime per video.
- CPU, memory and disk profile.
- temporary file path.
- cleanup behavior.
- sample success output.
- sample failed output.

## Production Constraints

- The tool must run in a dedicated non-root worker container.
- The worker must not mount the Docker socket.
- The worker must not mount Dify directories.
- The worker must not receive Dify RDS, Redis, Cookie, or Gateway secrets.
- Invocation must use a fixed argument list with no shell string assembly.
- Output must be validated against the committed JSON schema.

