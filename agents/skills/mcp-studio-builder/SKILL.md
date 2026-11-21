---
name: mcp-studio-builder
description: Scaffolds, configures, and upgrades custom MCP servers for Symphony Agent Studio using mcp_scaffold_cli.py (--preset, 8 composable packs, --infra sps|sre) and Day-2 mcp_ctl.py build-up/trim-down commands.
---

# Symphony Agent Studio MCP Server Scaffolder (`mcp-studio-builder`)

Bootstrap, build up, trim down, harden, and maintain production-grade **`MCPServer` (`mcp>=2.3.0,<3.0.0`, `from mcp.server.mcpserver import MCPServer, Context`; `FastMCP` alias retained in `src.core`)** servers from `template-mcp` using the 100% Python 3.12 stdlib CLIs (`./scripts/mcp_scaffold_cli.py` for Day-0 scaffolding and `uv run mcp-ctl` / `scripts/mcp_ctl.py` for Day-2 lifecycle management).

## Canonical References
- **[`docs/MCP_SERVER_AND_APP_ARCHITECTURE_SPEC.md`](https://github.com/Symphony-Professional-Services/template-mcp/blob/master/docs/MCP_SERVER_AND_APP_ARCHITECTURE_SPEC.md)** — Dual-transport MCP runtime, lossless Spring AI schema sanitization, Circle of Trust, and platform limits (`30s` Agent Studio tool deadline).
- **[`docs/A2UI_EXTENSION_GUIDE.md`](https://github.com/Symphony-Professional-Services/template-mcp/blob/master/docs/A2UI_EXTENSION_GUIDE.md)** — Opt-in Dual-Host A2UI v1.0 inline surfaces, Symphony Client2 ADK companion workspace, and `❖ SDS Core UI` v1.0.0 token rules.
- **[`docs/OAUTH_SETUP_GUIDE.md`](https://github.com/Symphony-Professional-Services/template-mcp/blob/master/docs/OAUTH_SETUP_GUIDE.md)** — `MCPRuntime` `set_auth_verifier`, Symphony IDM JWKS OBO JWT validation (`"verify_sub": False`), and `CallerPrincipal` `ContextVar` propagation.
- **[`./references/deployment-environments.md`](./references/deployment-environments.md)** — Side-by-side comparison of SPS Sandbox (`sym-professional-services`) vs. SRE Enterprise GitOps (`sym-dev-use4-gke-01` / `sym-prod-use4-gke-01`).

---

## Day-0 Scaffolding CLI (`mcp_scaffold_cli.py`)

Always invoke `./scripts/mcp_scaffold_cli.py` in non-interactive mode rather than copying files or running ad-hoc text replacements manually:

```bash
python3 <path-to-skill-directory>/scripts/mcp_scaffold_cli.py \
  --name "<server-name>" \
  [--prefix "<path-prefix>"] \
  [--preset "<minimal|studio-connector|interactive-app|enterprise-ha>"] \
  [--type "<direct|rest-adapter|mcp-bridge>"] \
  [--auth "<api-key|idm-jwt>"] \
  [--db "<none|postgres>"] \
  [--symphony-room "<none|rsa|webhook>"] \
  [--redis] \
  [--scheduler] \
  [--metrics [--otel]] \
  [--a2ui] \
  [--infra "<sps|sym-professional-services|sre>"] \
  [--secrets "API_TOKEN,DB_PASS"] \
  --target "<target-directory-path>" \
  [--template-dir "<local-template-mcp-path>"] \
  [--sync-core [--force]]
```

### 4 Named Starter Presets (`--preset` / `uv run mcp-ctl preset <name>`)

| Preset | Included Packs & Target | Best For |
| :--- | :--- | :--- |
| **`minimal`** *(default)* | Headless core (`api-key` + showcase `example.py` `1 tool + 1 resource + 1 prompt` auto-pruned on first `add tool` / `add surface`, `sps`) | Fast single-purpose MCP tools & PoCs |
| **`studio-connector`** | `adapter:rest` + `auth:idm-jwt` (`sps`) | Authenticated REST API connectors for Agent Studio |
| **`interactive-app`** | `a2ui` + `symphony-room` (`rsa`) + `scheduler` (`sps`) | Rich Dual-Host A2UI v1.0 cards, room notifications, and async jobs |
| **`enterprise-ha`** | `a2ui` + `auth:idm-jwt` + `db:postgres` + `redis` + `metrics` + `infra:sre` | Multi-replica (`replicas: 2`) enterprise SRE production rollouts |

### All 8 Composable Feature Packs

1. **`a2ui` (`--a2ui` / `mcp-ctl add a2ui`)**: Installs `src/extensions/a2ui/` + `web/adk/` + `scripts/{token_audit.py,tokens.json,verify_ui_dom.py}`, stamps `{name}-{controller,view}.js` (including internal `APP_ID`), generates `SURFACE_TOKEN_SECRET`, and enables `--extra a2ui`.
2. **`auth` (`--auth idm-jwt` / `mcp-ctl add auth idm-jwt`)**: Generates `src/tools/auth_jwt.py` with least-privilege RBAC (`frozenset({"viewer"})` by default; `{"viewer", "operator"}` only on explicit write/operator/admin scopes or `IDM_DEFAULT_ROLE=operator`), `RS256,RS512,ES256` JWKS verification, `/.well-known/oauth-protected-resource`, and `--extra auth`.
3. **`db` (`--db postgres` / `mcp-ctl add db postgres`)**: Generates `src/tools/db.py` (`psycopg_pool.AsyncConnectionPool` on `runtime.lifespan` + `@runtime.readiness("postgres")` + `check_database_health`), `docker-compose.postgres.yml`, `migrations/001_init.sql`, `--extra postgres`, and mounts `bot-db-credentials` at `/app/credentials/db` (`DATABASE_URL_FILE`) in SRE `values.yaml`.
4. **`adapter` (`--type rest-adapter|mcp-bridge` / `mcp-ctl add adapter <rest|mcp-bridge>`)**: Generates `src/tools/downstream_adapter.py` (`rest`) and/or `src/tools/mcp_bridge.py` (`mcp-bridge`) — both adapters can be active simultaneously.
5. **`symphony-room` (`--symphony-room rsa|webhook` / `mcp-ctl add symphony-room [--webhook]`)**: Generates `src/tools/symphony_room.py` supporting RSA Service-Account REST (`RS512` `<=290s` JWT, cached `sessionToken`/`keyManagerToken`, MessageML v2 + optional A2UI EntityJSON card) and Webhook delivery (`SYMPHONY_WEBHOOK_URL` + `SYMPHONY_WEBHOOK_SECRET` Bearer/HMAC).
6. **`redis` (`--redis` / `mcp-ctl add redis`)**: Generates `src/tools/redis_ha.py` (`redis.asyncio` on `runtime.lifespan` + `PING` `/ready` probe), wires `configure_cache_backend`, conditionally wires `configure_external_state_backend` + atomic `GETDEL` `configure_external_cot_store` when A2UI is enabled, writes `docker-compose.redis.yml`, enables `--extra redis`, and scales K8s/SRE manifests to `replicas: 2`.
7. **`scheduler` (`--scheduler` / `mcp-ctl add scheduler`)**: Generates zero-dep `src/tools/scheduler.py` with a stdlib 5-field cron matcher, `BackgroundJobRunner` for tasks exceeding Studio's `30s` limit (`submit_background_job`, `get_job_status`, `list_scheduled_jobs`), and optional A2UI `execution_progress` card rendering.
8. **`metrics` (`--metrics [--otel]` / `mcp-ctl add metrics [--otel]`)**: Generates zero-dep `src/tools/metrics.py` mounting Prometheus `0.0.4` `GET /metrics`, injects K8s/SRE Prometheus scrape annotations, and optionally registers an OpenTelemetry OTLP span exporter via `register_span_hook` when `--otel` and `OTEL_EXPORTER_OTLP_ENDPOINT` are configured.

---

## Day-2 Build-Up, Authoring, Trim-Down & SRE Promotion (`uv run mcp-ctl`)

Every scaffolded repository includes `scripts/mcp_ctl.py` and Schema v2 `.template-manifest.json` tracking `managed_files` and `pack_owned_files` SHA-256 digests:

```bash
# Inspect active profile, packs, extras, and modified files
uv run mcp-ctl status [--json]

# Apply a named preset on Day-2
uv run mcp-ctl preset <minimal|studio-connector|interactive-app|enterprise-ha>

# Build up composable packs incrementally
uv run mcp-ctl add a2ui
uv run mcp-ctl add auth idm-jwt
uv run mcp-ctl add db postgres
uv run mcp-ctl add adapter rest
uv run mcp-ctl add adapter mcp-bridge
uv run mcp-ctl add symphony-room [--webhook]
uv run mcp-ctl add redis
uv run mcp-ctl add scheduler
uv run mcp-ctl add metrics [--otel]
uv run mcp-ctl add secret API_TOKEN,DB_PASS

# Scaffold typed domain tools (auto-prunes unmodified example.py!) & custom A2UI surfaces
uv run mcp-ctl add tool lookup_trade [--module trades] [--read-only|--mutating|--destructive] [--cached]
uv run mcp-ctl add surface portfolio_summary [--archetype overview_stats]

# Remove individual packs or trim all optional packs (fail-safe dirty check exits 2 if edited!)
uv run mcp-ctl remove <pack> [--archive | --force]
uv run mcp-ctl trim minimal [--archive | --force]

# Promote from SPS Sandbox to SRE 3-repo GitOps (or switch infra)
uv run mcp-ctl promote sre
uv run mcp-ctl set-infra <sps|sre>

# Pull upstream src/core & DX script fixes without touching src/tools/
uv run mcp-ctl sync-core [--template-dir <path>] [--force]
```

### Fail-Safe Dirty Check (`--archive` / `--force`)
When removing a pack or running `trim minimal`, `mcp-ctl` verifies SHA-256 checksums of every file in `pack_owned_files`:
- If any pack file was edited by the developer, `mcp-ctl` **aborts with exit code `2`** and lists the modified paths.
- Pass `--archive` to move modified files safely into `.archive/<UTC_TIMESTAMP>/` (gitignored) before completing removal, or `--force` to delete them. Custom user domain tool modules in `src/tools/` are always preserved via AST-based `src/tools/__init__.py` updates.

---

## Verification Workflow After Scaffolding or Reconciling

```bash
make setup        # uv sync --locked --all-extras (+ npm ci && build if --a2ui)
make status       # uv run mcp-ctl status
make doctor       # python3 scripts/mcp_doctor.py --strict
make lint         # uv run ruff check --config pyproject.toml . && ruff check --select S --ignore S603,S607 src scripts
make test         # uv run pytest -v -k "not impeccable"
make smoke        # End-to-end HTTP/SSE & Streamable-HTTP black-box smoke check
```
