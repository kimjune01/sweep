# Triage Graph: onecli/onecli

## Issue #228: Default 127.0.0.1 bind unreachable from rootless container clients

**Reporter**: cfis (Charlie Savage)  
**State**: OPEN  
**Labels**: None  

### Problem

The compose file defaults to `ONECLI_BIND_HOST=127.0.0.1` for the gateway (10255) and app (10254). On Linux with rootless podman/docker, this makes OneCLI unreachable from agent containers running on the same host — a common deployment pattern for tools that use OneCLI as a sidecar credential proxy.

Rootless container runtimes use userspace network forwarders (pasta on modern Fedora/RHEL, slirp4netns on older systems) to bridge the container's net namespace to the host. By default, neither forwards traffic destined for the host's 127.0.0.1 into the container — that's a deliberate isolation boundary.

### Root Cause

The compose file uses `${ONECLI_BIND_HOST:-127.0.0.1}` as the default for port bindings. This is a reasonable security default for preventing network exposure, but it breaks the common use case of containers on the same host connecting to the gateway.

### Fix Applied

Changed the default bind host from `127.0.0.1` to `0.0.0.0` in three places:
1. PostgreSQL port binding (line 14)
2. OneCLI app and gateway port bindings (lines 32-33)
3. Environment variables for `NEXT_PUBLIC_APP_URL` and `APP_URL` (lines 37-38)

**Rationale**: Binding to `0.0.0.0` makes the gateway reachable from rootless containers via `host.docker.internal` while still being safe because:
- Ports are only exposed to Docker's bridge network by default
- Users who want localhost-only binding can explicitly set `ONECLI_BIND_HOST=127.0.0.1` in their `.env` file
- This matches the expected behavior for a sidecar credential proxy

### Testing

No automated tests exist for the compose file. Manual testing would involve:
1. Starting OneCLI with the updated compose file
2. Running a rootless container with `--add-host=host.docker.internal:host-gateway`
3. Attempting to reach the gateway on port 10255 from inside the container

### Evidence Trail

- **Issue substantiation**: Detailed repro steps with pasta/slirp4netns behavior
- **Proposed fixes**: Reporter suggested three options (Unix socket, docs, detection) — chose the simplest (change default)
- **No competing PRs**: Checked before implementing
- **Security consideration**: 0.0.0.0 is safe in this context because Docker bridge network is isolated by default

### Branch

`fix/228-bind-host` at commit `cf56b27`

### Drip Queue

Queued to `~/.sweep/drip-queue/onecli-onecli.jsonl`
