---
name: mcp-authoring
description: Author, extend, and document domain tools, resources, prompts, runtime hooks, and optional Dual-Host A2UI v1.0 surfaces inside a template-mcp repository, and deterministically generate MCP_SPEC.md via Python AST.
---

# Symphony MCP Authoring & Specification Skill (`template-mcp`)

Use this skill whenever adding or modifying MCP tools (`@mcp.tool()`), resources (`@mcp.resource()`), prompts (`@mcp.prompt()`), `MCPRuntime` hooks, outbound HTTP clients, OAuth/IDM caller checks, or Dual-Host A2UI v1.0 surfaces in a `template-mcp` server, and when generating or verifying `MCP_SPEC.md`.

---

## 1. Architectural Boundaries (Never Edit `src/core/`)

- **`src/core/` is immutable**: Built on **`mcp>=2.3.0,<3.0.0`** (`from mcp.server.mcpserver import MCPServer, Context`, with `FastMCP` retained as a backward-compatible alias in `src.core`). Never modify files in `src/core/`. Pull upstream security and protocol updates via `uv run mcp-ctl sync-core` (or `python3 skills/mcp-studio-builder/scripts/mcp_scaffold_cli.py --sync-core --target .`).
- **`src/tools/` owns domain capabilities**: Create focused modules under `src/tools/<domain>.py` (or `uv run mcp-ctl add tool <name>`) and export every module in `src/tools/__init__.py` (`__all__`).
- **`src/extensions/a2ui/` is opt-in**: Loaded by `src/app.py` only when `ENABLE_A2UI=true` (present when scaffolded with `--a2ui` or `uv run mcp-ctl add a2ui`).

---

## 2. Authoring Tools, Resources & Prompts (`src/tools/`)

### 2.1 Canonical Tool, Resource & Prompt Pattern

```python
from __future__ import annotations

import logging
from typing import Annotated

from pydantic import BaseModel, Field

from src.core import (
    Context,
    OAuthClientCredentialsAuth,
    PageResult,
    READ_ONLY_EXTERNAL_TOOL,
    ToolAnnotations,
    ToolExecutionError,
    cached_tool,
    decode_cursor,
    encode_cursor,
    get_caller_principal,
    get_http_client,
    get_secret,
    mcp,
    tool_guard,
)

logger = logging.getLogger(__name__)


class ServiceOrderResult(BaseModel):
    order_id: str = Field(description="Unique order identifier")
    status: str = Field(description="Current lifecycle status")
    requested_by: str = Field(description="Authenticated caller subject")


@mcp.tool(annotations=READ_ONLY_EXTERNAL_TOOL)
@tool_guard(timeout_seconds=26.0)
@cached_tool(ttl_seconds=30.0, scope="principal")
async def get_service_order(
    order_id: Annotated[str, Field(description="Order identifier, e.g. 'ORD-9042'")],
) -> ServiceOrderResult:
    """Fetch live order status from the upstream operations API when a user asks about an order."""
    if not order_id.strip():
        raise ToolExecutionError("invalid_order_id", "Order ID is required.", suggestion="Pass 'ORD-9042'.")
    principal = get_caller_principal()
    api_token = get_secret("OPS_API_TOKEN")
    client = get_http_client()  # 3s connect / 25s read (5s inside Studio's 30s CAIP-927 limit)

    resp = await client.get(
        f"https://ops.example.internal/v1/orders/{order_id}",
        headers={
            "Authorization": f"Bearer {api_token}",
            "X-On-Behalf-Of": principal.subject if principal else "system",
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    return ServiceOrderResult(
        order_id=str(payload["id"]),
        status=str(payload["status"]),
        requested_by=principal.subject if principal else "anonymous",
    )


@mcp.resource("config://ops/regions")
def list_supported_regions() -> str:
    """Return read-only operational region metadata for LLM planning context."""
    return '{"regions": ["us-east4", "us-central1", "eu-west2"]}'


@mcp.prompt()
def incident_review_prompt(service_name: str, window_minutes: int = 60) -> str:
    """Standardized operational prompt advertised via prompts/list."""
    return f"Inspect {service_name} over the last {window_minutes}m and summarize anomalies and mitigation steps."
```

### 2.2 Five Non-Negotiable Authoring Rules

1. **Use `@mcp.prompt()`, NEVER `@server.list_prompts()`**: Always decorate prompts with `@mcp.prompt()` on `src.core.mcp` (`MCPServer`) so `MCPServer` builds argument schemas properly. Pass `annotations=READ_ONLY_TOOL` (or `ToolAnnotations(read_only_hint=..., destructive_hint=..., idempotent_hint=..., open_world_hint=...)`) on every `@mcp.tool(...)`.
2. **Spring AI Schema Compatibility**: Always annotate arguments with concrete types and `Field(description=...)`. `src/core/sanitizer.py` losslessly strips `"default": null` and flattens nullable `T | None = None` unions while preserving `title`, `description`, `items`, `enum`, and `$ref`.
3. **Use `get_http_client()` (`25s` Budget) & `OAuthClientCredentialsAuth`**: Never create per-call `httpx.AsyncClient()` or call blocking `requests`. `get_http_client()` pools connections across the ASGI lifespan, honors SRE Secure Web Proxy (`HTTPS_PROXY` / `NO_PROXY` via `trust_env=True`), disables open redirects (`follow_redirects=False`), and caps reads at `25.0s` (`5s` inside Agent Studio's `30s` `CAIP-927` ceiling).
4. **Use `get_secret("NAME")` for All Credentials**: Resolves `${NAME}_FILE` -> `/app/credentials/mcp/${NAME}` (raw or JSON Secret Manager bundles) -> `/app/credentials/${kebab}` -> `os.getenv(NAME)` so code promotes from local `.env` to SPS K8s Secrets to SRE ExternalSecrets without code edits.
5. **Zero `stdout` Output**: Never call `print()`. Log via `logging.getLogger(__name__)` (routed strictly to `sys.stderr` with query-secret redaction).

---

## 3. Lifecycle, Readiness, Routes & Auth Hooks (`runtime`)

Compose custom infrastructure into Starlette without touching `src/core/`:

```python
from contextlib import asynccontextmanager
from starlette.requests import Request
from starlette.routing import Route
from src.core import CallerPrincipal, runtime


@runtime.lifespan
@asynccontextmanager
async def db_pool_lifespan(_app):
    # Runs ONCE per server process inside Starlette(lifespan=...), never per stateless HTTP request!
    pool = await create_pool()
    try:
        yield
    finally:
        await pool.close()


@runtime.readiness("postgres")
async def check_postgres() -> tuple[bool, str]:
    await pool.execute("SELECT 1")
    return True, "ok"


async def custom_jwt_verifier(request: Request) -> CallerPrincipal | None:
    # Return CallerPrincipal on valid JWT, or None to fall back to MCP_API_KEY
    ...


runtime.set_auth_verifier(custom_jwt_verifier)
runtime.add_routes([Route("/api/v1/webhook", endpoint=..., methods=["POST"])], include_prefixed=True)
```

For complete Symphony IDM JWKS verification (`"verify_sub": False` + `"require": ["exp"]` on PyJWT `>= 2.12`), see [`docs/OAUTH_SETUP_GUIDE.md`](https://github.com/Symphony-Professional-Services/template-mcp/blob/master/docs/OAUTH_SETUP_GUIDE.md).

---

## 4. Authoring Dual-Host A2UI v1.0 Surfaces (`ENABLE_A2UI=true`)

When `--a2ui` / `ENABLE_A2UI=true` is enabled, tools can render interactive cards simultaneously in **Symphony Client2** (`com.symphony.a2ui.surface` + `#a2ui=` 0-RTT hydration) and **Claude / SEP-1865 MCP App Hosts** (`ui://<slug>/a2ui/...`):

1. **Reuse or Register Surface Archetypes**:
   - Use the 5 built-in archetypes (`overview_stats`, `progressive_wizard`, `execution_progress`, `item_receipt_list`, `approval_gate`) via `render_a2ui_surface(surface_type=..., context=...)`, or
   - Register custom builders via `register_surface_archetype(surface_type, builder_fn, preferred_height=340)` and async action handlers via `register_surface_action(action_name, handler_fn, surface_type=..., operator_only=True)` from `src.extensions.a2ui.surfaces`.
2. **Enforce Scoped Token RBAC**:
   - Issue short-lived HMAC-SHA256 `st_...` tokens via `mint_surface_token(sub=..., role=..., tid=..., srf=surface_scope_for(surface_type))`.
   - Operator mutations (`operator_only=True`) require `operator`/`admin` role; CoT-issued `mint_portal_token` (`pt_...`) recipients receive `403`, and unsigned `pt_...` strings fail closed with `401`.
3. **Obey ExtensionML & `❖ SDS Core UI` v1.0.0 Invariants**:
   - Symphony ExtensionML `<iframe>` tags permit **only** `<entity><iframe src="..." width="460px" height="..."/></entity>` (`<= 1000px`, `&amp;` XML-escaped; zero `id`, `class`, `style`, or `allow*`).
   - Style strictly with `symphony-tokens.css` (Layer 1, never edit) + `app-tokens.css` / `a2ui-renderer.css` (`var(--sds-*)` primitives only, `>= 12px` text, `tabular-nums`, Sentence-case `--radius-pill` buttons, `0` raw hexes, `0` external CDN scripts). Validate with `make audit` (`python3 scripts/token_audit.py src/extensions/a2ui/static --strict` in child repos, or `python3 skills/symphony-ui-design/scripts/token_audit.py src/extensions/a2ui/static --strict` in `template-mcp`).

Full copy-paste surface builder walkthrough: [`docs/A2UI_EXTENSION_GUIDE.md`](https://github.com/Symphony-Professional-Services/template-mcp/blob/master/docs/A2UI_EXTENSION_GUIDE.md).

---

## 5. Deterministic `MCP_SPEC.md` Generation (`generate_mcp_spec.py`)

Never hand-maintain tool tables in `MCP_SPEC.md`. `generate_mcp_spec.py` (auto-discovered at `skills/mcp-authoring/scripts/generate_mcp_spec.py` in `template-mcp` or `.agents/skills/mcp-authoring/scripts/generate_mcp_spec.py` in scaffolded child repos via `make spec`) extracts `@mcp.tool(annotations=...)` presets (`READ_ONLY_TOOL`, `READ_ONLY_EXTERNAL_TOOL`, `IDEMPOTENT_WRITE_TOOL`, `DESTRUCTIVE_WRITE_TOOL`, or `ToolAnnotations(read_only_hint=..., ...)`) directly into the **`Safety`** column:

```bash
# Preview generated Markdown specification to stdout
python3 skills/mcp-authoring/scripts/generate_mcp_spec.py --repo . --stdout

# Write / update MCP_SPEC.md in the repository root (or run `make spec`)
python3 skills/mcp-authoring/scripts/generate_mcp_spec.py --repo . --output MCP_SPEC.md

# CI drift gate: exits non-zero if MCP_SPEC.md is missing or out of sync with AST
python3 skills/mcp-authoring/scripts/generate_mcp_spec.py --repo . --check
```

---

## 6. Fast Coding-Agent Loop (`mcp-ctl`, `mcp_doctor.py` & `mcp_call.py`)

Always validate new tools, resources, and prompts in-process (`<0.3s`) and run the AST Studio linter before committing:

```bash
# 1. List tools (with safety annotations & schemas), resources, and prompts
uv run mcp-ctl tools
python3 scripts/mcp_call.py --list --json

# 2. Invoke a tool, resource, or prompt in-process with optional CallerPrincipal OBO simulation
uv run mcp-ctl call --tool example_template_tool --args '{"arg": "hello"}' --principal alice:operator
python3 scripts/mcp_call.py --resource "config://server/status"
python3 scripts/mcp_call.py --prompt example_diagnostic_prompt --args '{"topic": "latency"}'

# 3. Run the two-tier stdlib AST Studio-compatibility doctor (MCP001–MCP009) & golden agent evals
uv run mcp-ctl doctor            # ERROR tier fails (exit 1); WARN tier advises (exit 0)
uv run mcp-ctl doctor --strict   # Promotes WARN tier (MCP005 raw env secrets, MCP007 missing annotations) to exit 1
uv run mcp-ctl eval              # Runs tests/test_agent_evals.py when studio-agent pack is installed
```
