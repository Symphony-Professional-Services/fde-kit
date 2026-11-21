#!/usr/bin/env python3
"""Deterministic stdlib-only AST generator for Symphony MCP_SPEC.md documentation.

Parses ``src/tools/**/*.py``, ``src/app.py``, and (when ``ENABLE_A2UI=true`` or
``--include-a2ui`` is supplied) ``src/extensions/a2ui/mcp_bindings.py`` using Python's
built-in ``ast`` module — requiring zero runtime third-party imports.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback for macOS Xcode Python <3.11
    tomllib = None  # type: ignore[assignment]

_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes"})
_CORE_SECRETS: frozenset[str] = frozenset(
    {"MCP_API_KEY", "SURFACE_TOKEN_SECRET", "PORTAL_TOKEN_SECRET"}
)
_ANNOTATION_PRESET_LABELS: dict[str, str] = {
    "READ_ONLY_TOOL": "read-only",
    "READ_ONLY_EXTERNAL_TOOL": "read-only (open-world)",
    "IDEMPOTENT_WRITE_TOOL": "idempotent-write",
    "DESTRUCTIVE_WRITE_TOOL": "destructive-write",
}


def resolve_spec_generator_path(repo_root: Path) -> Path | None:
    """Auto-discover ``generate_mcp_spec.py`` in either ``template-mcp`` or child ``.agents/skills`` layout."""
    for rel in (
        Path("skills/mcp-authoring/scripts/generate_mcp_spec.py"),
        Path(".agents/skills/mcp-authoring/scripts/generate_mcp_spec.py"),
    ):
        candidate = repo_root / rel
        if candidate.is_file():
            return candidate
    return None


def resolve_spec_generator_relpath(repo_root: Path) -> str:
    found = resolve_spec_generator_path(repo_root)
    if found is not None and found.is_relative_to(repo_root):
        return found.relative_to(repo_root).as_posix()
    return "skills/mcp-authoring/scripts/generate_mcp_spec.py"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    annotation: str
    default: str | None = None
    description: str = ""

    def format_signature(self) -> str:
        base = f"{self.name}: {self.annotation}" if self.annotation else self.name
        if self.default is not None:
            return f"{base} = {self.default}"
        return base


@dataclass(frozen=True)
class ToolSpec:
    name: str
    params: tuple[ParamSpec, ...]
    return_type: str
    description: str
    is_async: bool
    source_file: str
    safety: str = "unspecified"


@dataclass(frozen=True)
class ResourceSpec:
    uri: str
    name: str
    mime_type: str
    description: str
    source_file: str


@dataclass(frozen=True)
class PromptSpec:
    name: str
    params: tuple[ParamSpec, ...]
    description: str
    source_file: str


@dataclass
class ExtractedCatalog:
    tools: list[ToolSpec] = field(default_factory=list)
    resources: list[ResourceSpec] = field(default_factory=list)
    prompts: list[PromptSpec] = field(default_factory=list)
    secrets: set[str] = field(default_factory=set)


def _normalize_slug(app_name: str) -> str:
    if not app_name or app_name in {"APP_NAME", "{{APP_NAME}}"}:
        return "template-mcp"
    slug = re.sub(r"[^a-z0-9-]+", "-", app_name.strip().lower()).strip("-")
    return slug or "template-mcp"


def _parse_dotenv_file(dotenv_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not dotenv_path.is_file():
        return values
    try:
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def _resolve_repo_metadata(
    repo_root: Path,
    *,
    name_override: str = "",
    prefix_override: str = "",
    host_override: str = "",
    force_a2ui: bool = False,
) -> tuple[str, str, str, bool]:
    dotenv_vals = {
        **_parse_dotenv_file(repo_root / ".env.example"),
        **_parse_dotenv_file(repo_root / ".env"),
    }

    pyproject_name = ""
    pyproject_path = repo_root / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            raw_toml = pyproject_path.read_text(encoding="utf-8")
            if tomllib is not None:
                parsed_toml = tomllib.loads(raw_toml)
                pyproject_name = str(parsed_toml.get("project", {}).get("name", "")).strip()
            else:
                match_name = re.search(r'(?m)^name\s*=\s*["\']([^"\']+)["\']', raw_toml)
                pyproject_name = match_name.group(1).strip() if match_name else ""
        except Exception:
            pyproject_name = ""

    raw_name = (
        name_override.strip()
        or os.getenv("APP_NAME", "").strip()
        or dotenv_vals.get("APP_NAME", "").strip()
        or pyproject_name
        or repo_root.resolve().name
    )
    if raw_name in {"", "APP_NAME", "{{APP_NAME}}"}:
        raw_name = pyproject_name or repo_root.resolve().name or "template-mcp"

    raw_prefix = (
        prefix_override.strip()
        or os.getenv("PATH_PREFIX", "").strip()
        or dotenv_vals.get("PATH_PREFIX", "").strip()
    )
    if raw_prefix in {"", "APP_PATH_PREFIX", "/APP_PATH_PREFIX", "{{PATH_PREFIX}}"}:
        resolved_prefix = f"/mcp/{_normalize_slug(raw_name)}/v1"
    else:
        resolved_prefix = "/" + raw_prefix.strip("/")

    raw_host = (
        host_override.strip()
        or os.getenv("PUBLIC_BASE_URL", "").strip()
        or dotenv_vals.get("PUBLIC_BASE_URL", "").strip()
        or "https://mss.uat.symphony.com"
    )
    if not raw_host.startswith(("http://", "https://")):
        raw_host = f"https://{raw_host}"
    resolved_base_url = raw_host.rstrip("/")

    env_a2ui = os.getenv("ENABLE_A2UI", dotenv_vals.get("ENABLE_A2UI", "false")).strip().lower()
    a2ui_active = force_a2ui or (env_a2ui in _TRUTHY)
    return raw_name, resolved_prefix, resolved_base_url, a2ui_active


def _decorator_kind_and_call(dec: ast.expr) -> tuple[str | None, ast.Call | None]:
    call_node = dec if isinstance(dec, ast.Call) else None
    target = dec.func if isinstance(dec, ast.Call) else dec

    attr_name: str | None = None
    owner_name: str | None = None
    if isinstance(target, ast.Attribute):
        attr_name = target.attr
        if isinstance(target.value, ast.Name):
            owner_name = target.value.id
    elif isinstance(target, ast.Name):
        attr_name = target.id

    if owner_name not in {None, "mcp", "server", "effective_mcp", "mcp_instance"}:
        return None, None
    if attr_name in {"tool", "resource", "prompt"}:
        return attr_name, call_node
    return None, None


def _eval_string_expr(node: ast.expr | None, app_slug: str) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                expr_src = ast.unparse(value.value).strip()
                if expr_src in {"slug", "app_slug", "config.app_name"}:
                    parts.append(app_slug)
                else:
                    parts.append(f"{{{expr_src}}}")
        return "".join(parts)
    return ast.unparse(node)


def _extract_kwarg_str(call_node: ast.Call | None, key: str, app_slug: str) -> str:
    if call_node is None:
        return ""
    for kw in call_node.keywords:
        if kw.arg == key:
            return _eval_string_expr(kw.value, app_slug)
    return ""


def _first_flag(flags: dict[str, bool | None], *keys: str) -> bool | None:
    for key in keys:
        if key in flags and flags[key] is not None:
            return flags[key]
    return None


def _classify_hint_flags(flags: dict[str, bool | None]) -> str:
    ro = _first_flag(flags, "read_only_hint", "readOnlyHint")
    dest = _first_flag(flags, "destructive_hint", "destructiveHint")
    idem = _first_flag(flags, "idempotent_hint", "idempotentHint")
    ow = _first_flag(flags, "open_world_hint", "openWorldHint")
    if ro is True:
        return "read-only (open-world)" if ow is True else "read-only"
    if dest is True:
        return "destructive-write"
    if idem is True:
        return "idempotent-write"
    if dest is False:
        return "additive-write"
    if ro is False:
        return "write"
    return "custom"


def _extract_tool_safety(call_node: ast.Call | None) -> str:
    if call_node is None:
        return "unspecified"
    ann_expr: ast.expr | None = None
    for kw in call_node.keywords:
        if kw.arg == "annotations":
            ann_expr = kw.value
            break
    if ann_expr is None or (isinstance(ann_expr, ast.Constant) and ann_expr.value is None):
        return "unspecified"

    if isinstance(ann_expr, ast.Name):
        return _ANNOTATION_PRESET_LABELS.get(ann_expr.id, ann_expr.id)
    if isinstance(ann_expr, ast.Attribute):
        return _ANNOTATION_PRESET_LABELS.get(ann_expr.attr, ann_expr.attr)
    if isinstance(ann_expr, ast.Call):
        flags: dict[str, bool | None] = {}
        for kw in ann_expr.keywords:
            if kw.arg and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool):
                flags[kw.arg] = kw.value.value
        return _classify_hint_flags(flags)
    if isinstance(ann_expr, ast.Dict):
        dict_flags: dict[str, bool | None] = {}
        for k_node, v_node in zip(ann_expr.keys, ann_expr.values, strict=False):
            if (
                isinstance(k_node, ast.Constant)
                and isinstance(k_node.value, str)
                and isinstance(v_node, ast.Constant)
                and isinstance(v_node.value, bool)
            ):
                dict_flags[k_node.value] = v_node.value
        return _classify_hint_flags(dict_flags)

    return ast.unparse(ann_expr).strip() or "unspecified"


def _is_annotated_subscript(node: ast.expr) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    val = node.value
    if isinstance(val, ast.Name) and val.id == "Annotated":
        return True
    return (
        isinstance(val, ast.Attribute)
        and val.attr == "Annotated"
        and isinstance(val.value, ast.Name)
        and val.value.id in {"typing", "typing_extensions"}
    )


def _extract_annotated_parts(node: ast.Subscript) -> tuple[str, str]:
    elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if not elts:
        return "Any", ""
    inner_type, inner_desc = _unwrap_annotated(elts[0])
    desc = inner_desc
    for meta_elt in elts[1:]:
        if isinstance(meta_elt, ast.Call):
            for kw in meta_elt.keywords:
                if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                    desc = str(kw.value.value)
                    break
    return inner_type, desc


def _unwrap_annotated(annotation: ast.expr | None) -> tuple[str, str]:
    if annotation is None:
        return "Any", ""
    if _is_annotated_subscript(annotation):
        return _extract_annotated_parts(annotation)  # type: ignore[arg-type]
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        left_is_none = isinstance(annotation.left, ast.Constant) and annotation.left.value is None
        right_is_none = isinstance(annotation.right, ast.Constant) and annotation.right.value is None
        if right_is_none and _is_annotated_subscript(annotation.left):
            base_t, desc = _extract_annotated_parts(annotation.left)  # type: ignore[arg-type]
            return f"{base_t} | None", desc
        if left_is_none and _is_annotated_subscript(annotation.right):
            base_t, desc = _extract_annotated_parts(annotation.right)  # type: ignore[arg-type]
            return f"{base_t} | None", desc
    if (
        isinstance(annotation, ast.Subscript)
        and ast.unparse(annotation.value).strip() in {"Optional", "typing.Optional"}
        and _is_annotated_subscript(annotation.slice)
    ):
        base_t, desc = _extract_annotated_parts(annotation.slice)  # type: ignore[arg-type]
        return f"{base_t} | None", desc
    return ast.unparse(annotation), ""


def _is_context_type_str(ann_str: str) -> bool:
    cleaned = ann_str.removesuffix("| None").strip()
    return cleaned == "Context" or cleaned.endswith(".Context") or cleaned.startswith("Context[")


def _extract_params(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ParamSpec, ...]:
    args_obj = fn_node.args
    positional = list(args_obj.posonlyargs) + list(args_obj.args)
    pos_defaults: list[ast.expr | None] = [None] * (len(positional) - len(args_obj.defaults)) + list(
        args_obj.defaults
    )

    params: list[ParamSpec] = []
    for idx, arg_node in enumerate(positional):
        default_node = pos_defaults[idx]
        if arg_node.arg in {"self", "cls"}:
            continue
        ann_str, desc = _unwrap_annotated(arg_node.annotation)
        if _is_context_type_str(ann_str):
            continue
        default_str = ast.unparse(default_node) if default_node is not None else None
        params.append(
            ParamSpec(
                name=arg_node.arg,
                annotation=ann_str,
                default=default_str,
                description=desc,
            )
        )

    for idx, kw_arg in enumerate(args_obj.kwonlyargs):
        kw_default = args_obj.kw_defaults[idx]
        ann_str, desc = _unwrap_annotated(kw_arg.annotation)
        if _is_context_type_str(ann_str):
            continue
        default_str = ast.unparse(kw_default) if kw_default is not None else None
        params.append(
            ParamSpec(
                name=kw_arg.arg,
                annotation=ann_str,
                default=default_str,
                description=desc,
            )
        )

    return tuple(params)


def _clean_doc_summary(raw_doc: str | None) -> str:
    if not raw_doc:
        return "No description provided."
    collapsed = " ".join(line.strip() for line in raw_doc.strip().splitlines() if line.strip())
    return collapsed.replace("|", "\\|")


def _escape_md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


class _CatalogVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, app_slug: str, catalog: ExtractedCatalog) -> None:
        self._rel_path = rel_path
        self._app_slug = app_slug
        self._catalog = catalog

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_get_secret = (isinstance(func, ast.Name) and func.id == "get_secret") or (
            isinstance(func, ast.Attribute) and func.attr == "get_secret"
        )
        if is_get_secret and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            sec_name = node.args[0].value.strip()
            if sec_name and sec_name not in _CORE_SECRETS:
                self._catalog.secrets.add(sec_name)
        self.generic_visit(node)

    def _inspect_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            kind, call_node = _decorator_kind_and_call(dec)
            if kind is None:
                continue

            doc = _clean_doc_summary(ast.get_docstring(node))
            explicit_name = _extract_kwarg_str(call_node, "name", self._app_slug) or node.name
            params = _extract_params(node)
            ret_str = ast.unparse(node.returns) if node.returns is not None else "Any"

            if kind == "tool":
                self._catalog.tools.append(
                    ToolSpec(
                        name=explicit_name,
                        params=params,
                        return_type=ret_str,
                        description=doc,
                        is_async=isinstance(node, ast.AsyncFunctionDef),
                        source_file=self._rel_path,
                        safety=_extract_tool_safety(call_node),
                    )
                )
            elif kind == "resource":
                uri_val = ""
                if call_node and call_node.args:
                    uri_val = _eval_string_expr(call_node.args[0], self._app_slug)
                if not uri_val:
                    uri_val = _extract_kwarg_str(call_node, "uri", self._app_slug) or explicit_name
                mime_val = _extract_kwarg_str(call_node, "mime_type", self._app_slug) or "text/plain"
                self._catalog.resources.append(
                    ResourceSpec(
                        uri=uri_val,
                        name=explicit_name,
                        mime_type=mime_val,
                        description=doc,
                        source_file=self._rel_path,
                    )
                )
            elif kind == "prompt":
                self._catalog.prompts.append(
                    PromptSpec(
                        name=explicit_name,
                        params=params,
                        description=doc,
                        source_file=self._rel_path,
                    )
                )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._inspect_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._inspect_function(node)


def _resolve_active_tool_files(tools_dir: Path) -> list[Path]:
    """Return active ``src/tools/**/*.py`` files, filtering by ``src/tools/__init__.py`` imports when present."""
    all_py = [
        py_file
        for py_file in sorted(tools_dir.rglob("*.py"))
        if "__pycache__" not in py_file.parts and py_file.name != "__init__.py"
    ]
    init_path = tools_dir / "__init__.py"
    if not init_path.is_file():
        return all_py

    try:
        source = init_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(init_path))
    except (OSError, SyntaxError):
        return all_py

    if "iter_modules" in source or "import_module" in source:
        return all_py

    imported_top: set[str] = set()
    has_explicit_all = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if (node.level == 1 and not mod) or mod == "src.tools":
                for alias in node.names:
                    if alias.name != "*":
                        imported_top.add(alias.name)
            elif node.level == 1 and mod:
                imported_top.add(mod.split(".", 1)[0])
            elif mod.startswith("src.tools."):
                imported_top.add(mod.removeprefix("src.tools.").split(".", 1)[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src.tools."):
                    imported_top.add(alias.name.removeprefix("src.tools.").split(".", 1)[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    has_explicit_all = True

    if not imported_top and not has_explicit_all:
        return all_py

    filtered: list[Path] = []
    for py_file in all_py:
        rel_parts = py_file.relative_to(tools_dir).parts
        top_entry = rel_parts[0].removesuffix(".py")
        if top_entry in imported_top:
            filtered.append(py_file)
    return filtered


def extract_mcp_catalog(repo_root: Path, *, app_slug: str, include_a2ui: bool) -> ExtractedCatalog:
    catalog = ExtractedCatalog()
    candidate_files: list[Path] = []

    app_py = repo_root / "src" / "app.py"
    if app_py.is_file():
        candidate_files.append(app_py)

    tools_dir = repo_root / "src" / "tools"
    if tools_dir.is_dir():
        candidate_files.extend(_resolve_active_tool_files(tools_dir))

    if include_a2ui:
        a2ui_bindings = repo_root / "src" / "extensions" / "a2ui" / "mcp_bindings.py"
        if a2ui_bindings.is_file():
            candidate_files.append(a2ui_bindings)

    for file_path in candidate_files:
        try:
            source = file_path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source, filename=str(file_path))
            except SyntaxError:
                if hasattr(ast, "TypeAlias"):
                    raise
                shimmed = re.sub(
                    r"(?m)^(\s*)type\s+([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\n=]+\])?\s*=",
                    r"\1\2 =",
                    source,
                )
                shimmed = re.sub(
                    r"(?m)^(\s*(?:async\s+def|def|class)\s+[A-Za-z_][A-Za-z0-9_]*)\[[^\n\(:]+\]",
                    r"\1",
                    shimmed,
                )
                tree = ast.parse(shimmed, filename=str(file_path))
        except (OSError, SyntaxError) as exc:
            sys.stderr.write(f"[WARN] Skipping {file_path}: {exc}\n")
            continue
        rel_path = file_path.relative_to(repo_root).as_posix()
        _CatalogVisitor(rel_path=rel_path, app_slug=app_slug, catalog=catalog).visit(tree)

    return catalog


def render_markdown_spec(
    *,
    app_name: str,
    path_prefix: str,
    base_url: str,
    a2ui_active: bool,
    catalog: ExtractedCatalog,
    generator_relpath: str = "skills/mcp-authoring/scripts/generate_mcp_spec.py",
) -> str:
    full_prefix = f"{base_url}{path_prefix}"
    slug = _normalize_slug(app_name)

    lines: list[str] = [
        f"# Model Context Protocol (MCP) Server Specification: `{app_name}`",
        "",
        f"Auto-generated reference specification for integrating **`{app_name}`** with **Symphony Agent Studio** and authorized MCP hosts.",
        "",
        f"> _Generated deterministically via `{generator_relpath}` (Python `ast`). Do not hand-edit tool tables._",
        "",
        "---",
        "",
        "## 1. Endpoint & Transport Coordinates",
        "",
        "| Transport / Probe | Method | Target URL | Purpose |",
        "| :--- | :--- | :--- | :--- |",
        f"| **Streamable-HTTP (Primary)** | `POST`, `GET`, `DELETE` | `{full_prefix}/mcp` | Stateless JSON-RPC 2.0 (`initialize`, `tools/list`, `tools/call`, batch arrays) |",
        f"| **SSE Stream (Fallback)** | `GET` | `{full_prefix}/sse` | Opens persistent Server-Sent Events stream (`PUBLIC_PATH_PREFIX` relative endpoint) |",
        f"| **SSE Messages** | `POST` | `{full_prefix}/messages/` | Posts JSON-RPC messages to an active SSE `session_id` (`/messages` & `/messages/`) |",
        f"| **Liveness Probe** | `GET` | `{full_prefix}/healthcheck` | Unauthenticated container liveness check (`200 OK`) |",
        f"| **Readiness Probe** | `GET` | `{full_prefix}/ready` | Evaluates auth configuration & registered `@runtime.readiness` checks (`200` / `503`) |",
    ]

    if a2ui_active:
        lines.extend(
            [
                f"| **A2UI Surface Host** | `GET` | `{full_prefix}/app/a2ui-surface.html` | Opt-in 460px inline chat card & SEP-1865 surface renderer |",
                f"| **Companion Workspace** | `GET` | `{full_prefix}/app/index.html` | Symphony ADK left-nav & `SIDE_BY_SIDE` workspace |",
            ]
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 2. Authentication & Secret Contract",
            "",
            "### Inbound Authentication (`Client -> MCP Server`)",
            "- **Connection Vault Multi-Scheme API Key (`--auth api-key`)**: Constant-time `hmac.compare_digest` validation accepting `Authorization: Bearer <key>`, `Authorization: Basic <key>` (raw or RFC-7617 Base64), `Authorization: Token <key>`, and `X-MCP-API-KEY: <key>`.",
            "- **Symphony IDM / OIDC Bearer JWT (`--auth idm-jwt`)**: Verifies RS256/RS512 Bearer tokens via `runtime.set_auth_verifier(...)` (`verify_sub=False`, `require=[\"exp\"]`) and binds `CallerPrincipal` (`get_caller_principal()`).",
            "- **Reactive Refresh & Fail-Closed Policy**: Returns `401 Unauthorized` with `WWW-Authenticate: Bearer realm=\"mcp\"` on invalid/expired credentials, and `503 auth_unconfigured` if exposed on non-loopback interfaces without credentials.",
            "- **Studio Timeout Alignment (`CAIP-927`)**: Outbound `get_http_client()` calls enforce a `3.0s` connect / `25.0s` read budget inside Agent Studio's `30s` `MCP_REQUEST_TIMEOUT`.",
            "",
            "### Secret Resolution (`get_secret` File-First Parity)",
            "",
            "| Secret Name | SPS K8s Secret Key | SRE Mounted File Path | Purpose |",
            "| :--- | :--- | :--- | :--- |",
            f"| `MCP_API_KEY` | `{slug}-credentials.MCP_API_KEY` | `/app/credentials/mcp/MCP_API_KEY` | Shared inbound Connection Vault key |",
        ]
    )

    if a2ui_active:
        lines.append(
            f"| `SURFACE_TOKEN_SECRET` | `{slug}-credentials.SURFACE_TOKEN_SECRET` | `/app/credentials/mcp/SURFACE_TOKEN_SECRET` | HMAC-SHA256 signing key for `st_...` & `pt_...` tokens |"
        )

    for sec_name in sorted(catalog.secrets):
        lines.append(
            f"| `{sec_name}` | `{slug}-credentials.{sec_name}` | `/app/credentials/mcp/{sec_name}` | Downstream service credential (`get_secret`) |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 3. Available Tools Catalog (`{len(catalog.tools)}`)",
            "",
        ]
    )

    if not catalog.tools:
        lines.append("_No `@mcp.tool()` definitions found._")
    else:
        lines.extend(
            [
                "| Tool Name | Safety | Arguments | Returns | Source | Description |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
            ]
        )
        for tool in catalog.tools:
            if tool.params:
                args_cell = ", ".join(f"`{_escape_md_cell(p.format_signature())}`" for p in tool.params)
            else:
                args_cell = "_(none)_"
            safety_cell = f"`{_escape_md_cell(tool.safety)}`"
            ret_cell = f"`{_escape_md_cell(tool.return_type)}`"
            lines.append(
                f"| **`{tool.name}`** | {safety_cell} | {args_cell} | {ret_cell} | `{tool.source_file}` | {tool.description} |"
            )

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 4. Available Resources (`{len(catalog.resources)}`) & Prompts (`{len(catalog.prompts)}`)",
            "",
        ]
    )

    if catalog.resources:
        lines.extend(
            [
                "### Resources (`@mcp.resource`)",
                "",
                "| URI Template | MIME Type | Handler | Description |",
                "| :--- | :--- | :--- | :--- |",
            ]
        )
        for res in catalog.resources:
            lines.append(
                f"| `{_escape_md_cell(res.uri)}` | `{_escape_md_cell(res.mime_type)}` | `{res.name}` (`{res.source_file}`) | {res.description} |"
            )
        lines.append("")
    else:
        lines.extend(["_No `@mcp.resource()` definitions registered._", ""])

    if catalog.prompts:
        lines.extend(
            [
                "### Prompts (`@mcp.prompt`)",
                "",
                "| Prompt Name | Arguments | Source | Description |",
                "| :--- | :--- | :--- | :--- |",
            ]
        )
        for prm in catalog.prompts:
            p_args = (
                ", ".join(f"`{_escape_md_cell(p.format_signature())}`" for p in prm.params)
                if prm.params
                else "_(none)_"
            )
            lines.append(f"| **`{prm.name}`** | {p_args} | `{prm.source_file}` | {prm.description} |")
        lines.append("")
    else:
        lines.extend(["_No `@mcp.prompt()` definitions registered._", ""])

    lines.extend(
        [
            "---",
            "",
            "## 5. Quick Verification Probes",
            "",
            "```bash",
            "# 1. Liveness & readiness checks",
            f"curl -fsS {full_prefix}/healthcheck",
            f"curl -fsS {full_prefix}/ready",
            "",
            "# 2. Stateless Streamable-HTTP initialize probe",
            f'curl -fsS -X POST "{full_prefix}/mcp" \\',
            '  -H "Authorization: Bearer ${MCP_API_KEY}" \\',
            '  -H "Content-Type: application/json" \\',
            "  -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"spec-probe\",\"version\":\"1.0.0\"}}}'",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or verify MCP_SPEC.md deterministically from Python AST."
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Target MCP repository root directory (default: current directory).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output Markdown path (default: <repo>/MCP_SPEC.md).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print generated Markdown specification to stdout without writing files.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that the existing output file matches the freshly generated AST specification.",
    )
    parser.add_argument(
        "--include-a2ui",
        action="store_true",
        help="Include opt-in src/extensions/a2ui/mcp_bindings.py tools and ui:// resources regardless of ENABLE_A2UI.",
    )
    parser.add_argument("--name", default="", help="Optional server name override.")
    parser.add_argument("--prefix", default="", help="Optional PATH_PREFIX override.")
    parser.add_argument("--host", default="", help="Optional public base URL / ingress host override.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        sys.stderr.write(f"[ERROR] Repository directory not found: {repo_root}\n")
        return 2

    app_name, path_prefix, base_url, a2ui_active = _resolve_repo_metadata(
        repo_root,
        name_override=args.name,
        prefix_override=args.prefix,
        host_override=args.host,
        force_a2ui=args.include_a2ui,
    )
    catalog = extract_mcp_catalog(
        repo_root,
        app_slug=_normalize_slug(app_name),
        include_a2ui=a2ui_active,
    )
    gen_relpath = resolve_spec_generator_relpath(repo_root)
    rendered = render_markdown_spec(
        app_name=app_name,
        path_prefix=path_prefix,
        base_url=base_url,
        a2ui_active=a2ui_active,
        catalog=catalog,
        generator_relpath=gen_relpath,
    )

    if args.stdout:
        sys.stdout.write(rendered)
        return 0

    out_path = Path(args.output).resolve() if args.output else (repo_root / "MCP_SPEC.md")

    if args.check:
        if not out_path.is_file():
            sys.stderr.write(
                f"[FAIL] {out_path} does not exist. Run `python3 {gen_relpath} --repo {repo_root}` to generate it.\n"
            )
            return 1
        existing = out_path.read_text(encoding="utf-8")
        if existing.strip() != rendered.strip():
            sys.stderr.write(
                f"[FAIL] {out_path} is out of sync with Python AST definitions. Re-run without --check to update.\n"
            )
            return 1
        sys.stderr.write(f"[OK] {out_path} is up to date ({len(catalog.tools)} tools, {len(catalog.resources)} resources).\n")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    sys.stderr.write(f"[OK] Wrote {out_path} ({len(catalog.tools)} tools, {len(catalog.resources)} resources).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
