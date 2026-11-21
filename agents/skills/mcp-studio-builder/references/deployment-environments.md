# MCP Server Deployment Environments — SPS Sandbox vs. SRE Enterprise Fleet

Symphony MCP servers support two GCP/GKE target environments from the **exact same Python codebase** (`src/core/config.py:get_secret()` + `src/core/http_client.py:get_http_client()`), switchable at any time via `uv run mcp-ctl promote sre` or `uv run mcp-ctl set-infra <sps|sre>`:

1. **SPS Quick Test Sandbox (`--infra sps` / `sym-professional-services`)**: Self-service OIDC GitHub Actions deployment to `mss.uat.symphony.com` for rapid PoCs and UAT iteration.
2. **SRE Enterprise Fleet (`--infra sre` / `--preset enterprise-ha`)**: 3-repo GitOps deployment (`Proserve-Bots` -> `gke-namespaces-live` -> `bot-live`) on `sym-dev-use4-gke-01` (`dev-use4-001`) and `sym-prod-use4-gke-01` (`prod-use4-001`), coordinated via the workspace `sre-bot-deployment` skill.

---

## Side-by-Side Comparison

| Dimension | **SPS Sandbox (`--infra sps`)** | **SRE Enterprise Fleet (`--infra sre`)** |
| :--- | :--- | :--- |
| **GCP Project & Cluster** | `sym-professional-services` (`546286289894`), `dev-cluster` (`us-central1`) | `sym-dev-use4-gke-01` (`dev-use4-001`, `us-east4`) -> `sym-prod-use4-gke-01` (`prod-use4-001`) |
| **Repositories** | Standalone MCP repo (`mcps/<app>`) | 3-repo GitOps: `Proserve-Bots/psm-<short>`, `gke-namespaces-live`, `bot-live` (+ `symphony-datastore-tools` if Cloud SQL) |
| **Build & Deploy** | Self-hosted GHA runner (`[self-hosted, qa]`) via WIF OIDC (`dev-pool` / `mss-github-dev`) + `kubectl apply -k k8s/dev` | Jenkins Kaniko build (`python:3.12-noble`) + ArgoCD sync from `bot-live` |
| **Container Port** | `8000` (`Service` `80 -> 8000`) | `8080` (`Service` `443 -> 8080`, `konghq.com/protocol: "http"`) |
| **HA Scaling (`redis` pack)** | `replicas: 1` default; `replicas: 2` when `redis` HA pack is enabled | `replicaCount: 1` default; `replicaCount: 2` (`replicas: 2`) when `redis` HA pack is enabled |
| **Ingress & Path Prefix** | Gateway API `v1` `HTTPRoute` on `mss.uat.symphony.com` (`/mcp/<short>/v1`) | Kong Ingress on tenant domain (`konghq.com/strip-path: "false"`, `PATH_PREFIX=/mcp/psm-<short>-5079/v1`) |
| **In-Repo K8s Manifests** | `k8s/base` + `k8s/dev` (`1001:1001`, `readOnlyRootFilesystem: true`, `/tmp` `emptyDir`, `PUBLIC_BASE_URL` + `MCP_ALLOWED_HOSTS` on `mss.uat.symphony.com`, `NetworkPolicy`) | **None in app repo** (`SEC-D1-003` forbids `k8s/` in `Proserve-Bots`); copyable templates generated under `docs/sre-gitops/` |
| **Secret Management** | K8s Secret `<app>-credentials` upserted via stdin JSON (`--save-config=false`, preserving existing keys) | **100% ProServe Self-Service in Dev**: `ns_sym-dev-use4-gke-01_<ns>_mcp-credentials` mounted at `/app/credentials/mcp/*` + `bot-db-credentials` mounted at `/app/credentials/db/DATABASE_URL` when `--db postgres` (**zero `secretKeyRef` env vars**) |
| **Outbound Egress** | Direct HTTPS (`NetworkPolicy` ports `53`, `443`, `8080`, `5432`, `6379`, `4318`) | Explicit `ExtendedNamespace` egress (`datastores`, `privateManagedServices`, Secure Web Proxy `HTTPS_PROXY=http://10.48.4.66:8080`) |
| **Jira & Commit Prefixes** | `[MSS-XXXX]` Story/Epic on ProServe Board `2236` | **`[MSS-XXXX]`** on `Proserve-Bots` & routine Dev `bot-live`; **`[SRE-XXXXX]`** (`SRE` Jira `Story`) on `gke-namespaces-live` & `symphony-datastore-tools`; **`[ESS-XXXXX]`** (`ESS` `Change Request`) for Prod `prod-use4-001` |

---

## Zero-Code Portability Contract

Every server scaffolded from `template-mcp` runs unchanged across local `.env`, SPS K8s, and SRE GKE:

1. **File-First Secrets (`get_secret("KEY")`)**: Resolves `${KEY}_FILE` -> `/app/credentials/mcp/${KEY}` (raw or JSON Secret Manager bundle) -> `/app/credentials/${key}` -> `os.getenv("KEY")`. Switching from local `.env` or SPS `secretKeyRef` to SRE file-mounted volumes (`MCP_API_KEY_FILE`, `DATABASE_URL_FILE`, `REDIS_URL_FILE`) requires **zero Python changes**.
2. **Proxy-Aware Pooled HTTP (`get_http_client()`)**: Uses a lifespan-managed `httpx.AsyncClient(trust_env=True, verify=True, follow_redirects=False, timeout=Timeout(connect=3.0, read=25.0))` that honors SRE's `HTTPS_PROXY=http://10.48.4.66:8080` and `NO_PROXY` automatically while failing cleanly inside Agent Studio's `30s` tool timeout.
3. **Read-Only Root Filesystem & Immutable Code (`1001:1001`)**: Runs on `python:3.12-slim` (SPS) or `python:3.12-noble` (SRE) as non-root UID/GID `1001` via `/app/.venv/bin/python src/app.py`, with `/app/.venv` and `/app/src` owned by `root:root` (`a+rX,go-w`) and `HOME=/tmp` + `TMPDIR=/tmp` backed by a `64Mi` `emptyDir` volume.
4. **Unwrapped Health Probes**: `/healthcheck` (startup/liveness) and `/ready` (readiness, failing closed with `503` when auth or required dependencies are unconfigured on `0.0.0.0`) bypass `Host` header filtering so kubelet and GKE/Kong probers always succeed.

---

## SRE 3-Repo Onboarding Summary (`--infra sre` / `uv run mcp-ctl promote sre`)

Scaffolding with `--infra sre` (or running `uv run mcp-ctl promote sre`) generates ready-to-copy templates in `docs/sre-gitops/`:
1. **File an `SRE` Jira `Story`** (linked `relates to MSS-XXXX`) for Dev namespace merge (and Cloud SQL DB if `--db postgres`). Reserve `ESS` `Change Request` strictly for Production (`prod-use4-001`) CAB promotion.
2. **Run Security Pre-Flight** in `Proserve-Bots`: `infosec_audit.py` and `snyk_preflight.py` (**0 CRITICAL / 0 HIGH**).
3. **Open `gke-namespaces-live` PR #1 (`[SRE-XXXXX]`)** using `docs/sre-gitops/gke-namespaces-live/psm-<short>-5079.yaml` (keeping `argocd` commented out until `bot-live` merges).
4. **Create Self-Service Dev Secret(s)** in GCP Secret Manager (`ns_sym-dev-use4-gke-01_psm-<short>-5079_mcp-credentials`, plus `bot-db-credentials` when PostgreSQL is enabled) as `sym-sso-gcp-mss-admin@symphony.com`.
5. **Merge `Proserve-Bots` (`[MSS-XXXX]`) & `bot-live` (`[MSS-XXXX]`)** using `docs/sre-gitops/bot-live/{Chart.yaml,values.yaml}` (`sym-common` `0.8.6`), then uncomment `argocd` in `gke-namespaces-live` PR #2 (`[SRE-XXXXX]`).
