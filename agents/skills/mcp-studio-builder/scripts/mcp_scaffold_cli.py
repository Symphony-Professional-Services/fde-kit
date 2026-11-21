#!/usr/bin/env python3
"""Symphony AI Agent Studio MCP Server Scaffolder & Core Sync Engine.

100% Python 3.12 standard-library CLI for:
  1. Day-0 scaffolding of headless or Dual-Host A2UI v1.0 MCP servers using named presets
     (`--preset minimal|studio-connector|interactive-app|enterprise-ha`) and 8 composable
     feature packs (`--a2ui`, `--auth`, `--type`, `--db`, `--symphony-room`, `--redis`,
     `--scheduler`, `--metrics [--otel]`, `--infra sps|sre`, `--secrets`).
  2. Day-2 safe upgrades of managed runtime files via SHA-256 manifest diffing (`--sync-core`),
     coordinated with `scripts/mcp_ctl.py` on Schema v2 `.template-manifest.json`.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback for macOS system Python <3.11
    tomllib = None  # type: ignore[assignment]

MANIFEST_FILENAME = ".template-manifest.json"
NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9]))*$")
SECRET_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

_SKIP_TOP_LEVEL: frozenset[str] = frozenset(
    {
        ".git",
        "skills",
        "mcp_template_banner.png",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        ".env",
        "tests",
        "openspec",
        "requirements.lock",
        MANIFEST_FILENAME,
        ".mcp.json",
        ".archive",
    }
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scaffold or sync a hardened Symphony AI Agent Studio MCP Server."
    )
    parser.add_argument("--name", help="Unique server slug (PEP 508 lowercase + hyphens, e.g. tradefeedr-mcp)")
    parser.add_argument("--prefix", help="HTTP Gateway routing path prefix (e.g. /mcp/tradefeedr/v1)")
    parser.add_argument(
        "--preset",
        choices=["minimal", "studio-connector", "interactive-app", "enterprise-ha"],
        default=None,
        help="Named starter preset (can be combined with explicit pack flags)",
    )
    parser.add_argument(
        "--type",
        choices=["direct", "proxy", "rest-adapter", "mcp-bridge"],
        default=None,
        help="Tooling architecture: 'direct' (default), 'rest-adapter' ('proxy' alias), or 'mcp-bridge'",
    )
    parser.add_argument(
        "--auth",
        choices=["api-key", "idm-jwt"],
        default=None,
        help="Inbound authentication pack: 'api-key' (default) or 'idm-jwt' (dual Symphony IDM JWKS + API key)",
    )
    parser.add_argument(
        "--db",
        choices=["none", "postgres"],
        default=None,
        help="Database pack: 'none' (default) or 'postgres' (async psycopg_pool + /ready SELECT 1 probe)",
    )
    parser.add_argument(
        "--symphony-room",
        dest="symphony_room",
        choices=["none", "rsa", "webhook"],
        default=None,
        help="Outbound Symphony room messaging pack: 'none' (default), 'rsa', or 'webhook'",
    )
    parser.add_argument(
        "--redis",
        action="store_true",
        default=False,
        help="Enable Redis HA state upgrade (shared cache + A2UI state/CoT store + replicas: 2)",
    )
    parser.add_argument(
        "--scheduler",
        action="store_true",
        default=False,
        help="Enable zero-dep asyncio 5-field cron & background job runner (>30s Studio tasks)",
    )
    parser.add_argument(
        "--metrics",
        action="store_true",
        default=False,
        help="Enable zero-dep Prometheus /metrics endpoint & scrape annotations",
    )
    parser.add_argument(
        "--otel",
        action="store_true",
        default=False,
        help="With --metrics, enable optional OpenTelemetry [otel] OTLP span exporter extra",
    )
    parser.add_argument(
        "--infra",
        choices=["sps", "sym-professional-services", "sre"],
        default=None,
        help="Target deployment platform: 'sym-professional-services' ('sps' alias) or 'sre'",
    )
    parser.add_argument("--target", default="./", help="Target project directory")
    parser.add_argument(
        "--secrets",
        help="Comma-separated custom secret env var names (e.g. API_TOKEN,DB_PASS)",
    )
    parser.add_argument(
        "--a2ui",
        "--with-a2ui",
        dest="a2ui",
        action="store_true",
        default=False,
        help="Enable Dual-Host A2UI v1.0 & Symphony ADK extension (default: disabled unless in preset)",
    )
    parser.add_argument(
        "--template-dir",
        dest="template_dir",
        default=None,
        help="Optional local path to template-mcp directory (bypasses remote git clone)",
    )
    parser.add_argument(
        "--sync-core",
        dest="sync_core",
        action="store_true",
        default=False,
        help="Day-2 upgrade mode: sync managed src/core & DX scripts against .template-manifest.json",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="With --sync-core, overwrite locally modified managed files",
    )
    return parser.parse_args(argv)


def _load_mcp_ctl_module(template_dir: Path | None) -> Any:
    candidates: list[Path] = []
    if template_dir is not None:
        candidates.append(template_dir / "scripts" / "mcp_ctl.py")
    candidates.append(Path(__file__).resolve().parents[3] / "scripts" / "mcp_ctl.py")

    for script_path in candidates:
        if script_path.is_file():
            spec = importlib.util.spec_from_file_location("_mcp_ctl_shared", str(script_path))
            if spec is not None and spec.loader is not None:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
    sys.stderr.write("Error: Could not locate scripts/mcp_ctl.py in template-mcp blueprint.\n")
    sys.exit(1)


def resolve_template_source(
    explicit_template_dir: str | None,
    *,
    require_a2ui: bool = False,
) -> tuple[Path, bool]:
    if explicit_template_dir:
        resolved = Path(explicit_template_dir).resolve()
        if not resolved.is_dir():
            sys.stderr.write(f"Error: --template-dir does not exist: {resolved}\n")
            sys.exit(1)
        if not (resolved / "src" / "core" / "server.py").is_file():
            sys.stderr.write(f"Error: --template-dir is not a valid template-mcp checkout: {resolved}\n")
            sys.exit(1)
        if require_a2ui and not (resolved / "src" / "extensions" / "a2ui").is_dir():
            sys.stderr.write(
                f"Error: --template-dir does not contain A2UI extension assets (src/extensions/a2ui): {resolved}\n"
            )
            sys.exit(1)
        return resolved, False

    env_dir = os.getenv("MCP_TEMPLATE_DIR", "").strip()
    if env_dir:
        env_path = Path(env_dir).resolve()
        if not (env_path / "src" / "core" / "server.py").is_file():
            sys.stderr.write(f"Error: MCP_TEMPLATE_DIR is not a valid template-mcp checkout: {env_path}\n")
            sys.exit(1)
        if require_a2ui and not (env_path / "src" / "extensions" / "a2ui").is_dir():
            sys.stderr.write(
                f"Error: MCP_TEMPLATE_DIR does not contain A2UI extension assets (src/extensions/a2ui): {env_path}\n"
            )
            sys.exit(1)
        return env_path, False

    candidate_repo = Path(__file__).resolve().parents[3]
    if (candidate_repo / "src" / "core" / "server.py").is_file() and (candidate_repo / "pyproject.toml").is_file():
        if not require_a2ui or (candidate_repo / "src" / "extensions" / "a2ui").is_dir():
            try:
                raw_toml = (candidate_repo / "pyproject.toml").read_text(encoding="utf-8")
                if tomllib is not None:
                    proj_name = tomllib.loads(raw_toml).get("project", {}).get("name")
                else:
                    m = re.search(r'(?m)^name\s*=\s*["\']([^"\']+)["\']', raw_toml)
                    proj_name = m.group(1) if m else ""
                if proj_name == "template-mcp":
                    return candidate_repo, False
            except (OSError, ValueError):
                pass

    return Path(fetch_template_from_git()), True


def fetch_template_from_git() -> str:
    sys.stdout.write("\nConnecting to GitHub to fetch the latest template-mcp blueprint...\n")
    temp_dir = tempfile.mkdtemp(prefix="mcp_template_")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    git_bin = shutil.which("git") or "git"

    for label, url in (
        ("SSH", "git@github.com:Symphony-Professional-Services/template-mcp.git"),
        ("HTTPS", "https://github.com/Symphony-Professional-Services/template-mcp.git"),
    ):
        sys.stdout.write(f"Attempting clone via {label}...\n")
        res = subprocess.run(  # noqa: S603
            [git_bin, "clone", "--depth", "1", url, temp_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            check=False,
        )
        if res.returncode == 0:
            return temp_dir

    sys.stderr.write("Error: Failed to clone template-mcp repository via SSH or HTTPS.\n")
    shutil.rmtree(temp_dir, ignore_errors=True)
    sys.exit(1)


def prompt_interactive(ctl: Any) -> dict[str, Any]:
    sys.stdout.write("\nWelcome to the AI Agent Studio MCP Server Scaffolder!\n")
    sys.stdout.write("---------------------------------------------------------\n")
    while True:
        name = input("Enter Server Name (lowercase, hyphens only, e.g. tradefeedr-mcp): ").strip().lower()
        if name and NAME_PATTERN.fullmatch(name):
            break
        sys.stdout.write("Invalid name. Use lowercase alphanumeric characters and hyphens.\n")

    default_prefix = ctl.normalize_prefix(None, name)
    prefix = ctl.normalize_prefix(input(f"Enter Gateway Path Prefix [default: {default_prefix}]: "), name)
    preset_choice = input(
        "Select Starter Preset:\n"
        "  [1] minimal (Default)\n"
        "  [2] studio-connector (REST adapter + IDM JWT)\n"
        "  [3] interactive-app (A2UI + Symphony Room + Scheduler)\n"
        "  [4] enterprise-ha (A2UI + IDM JWT + Postgres + Redis HA + Metrics + SRE)\n"
        "Choose [1-4]: "
    ).strip()
    preset = {
        "2": "studio-connector",
        "3": "interactive-app",
        "4": "enterprise-ha",
    }.get(preset_choice, "minimal")
    target = input("Enter Target Scaffolding Directory [default: ./]: ").strip() or "./"
    secrets_raw = input("Custom secret env var names (comma-separated, optional): ").strip()
    return {
        "name": name,
        "prefix": prefix,
        "preset": preset,
        "target": target,
        "secrets_raw": secrets_raw,
    }


def copy_blueprint_files(src_dir: Path, target_dir: Path) -> None:
    real_src = os.path.realpath(src_dir)
    real_target = os.path.realpath(target_dir)
    if real_target == real_src:
        sys.stderr.write(
            f"Error: --target ({real_target}) cannot be the same directory as --template-dir ({real_src}).\n"
        )
        sys.exit(1)

    sys.stdout.write(f"Copying blueprint files to: {target_dir.resolve()}\n")
    entries = os.listdir(src_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    base_ignore = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
        ".DS_Store",
    )

    def _ignore_with_target(cur_dir: str, names: list[str]) -> set[str]:
        ignored = set(base_ignore(cur_dir, names))
        for n in names:
            if os.path.realpath(os.path.join(cur_dir, n)) == real_target:
                ignored.add(n)
        return ignored

    for item in entries:
        if item in _SKIP_TOP_LEVEL:
            continue
        s = src_dir / item
        if os.path.realpath(s) == real_target:
            continue
        d = target_dir / item
        if s.is_symlink():
            if os.path.lexists(d):
                d.unlink()
            os.symlink(os.readlink(s), d)
        elif s.is_dir():
            shutil.copytree(s, d, symlinks=True, ignore=_ignore_with_target, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)


def update_pyproject_and_lockfile(target_dir: Path, name: str) -> None:
    pyproj = target_dir / "pyproject.toml"
    if pyproj.is_file():
        txt = pyproj.read_text(encoding="utf-8")
        txt = re.sub(r'^name\s*=\s*"template-mcp"', f'name = "{name}"', txt, count=1, flags=re.MULTILINE)
        txt = txt.replace(
            'description = "Hardened MCP Server for template-mcp"',
            f'description = "Hardened MCP Server for {name}"',
        )
        txt = re.sub(r'"mcp\s*>=[^"]*"', '"mcp>=2.3.0,<3.0.0"', txt)
        pyproj.write_text(txt, encoding="utf-8")

    lock_path = target_dir / "uv.lock"
    if not lock_path.is_file():
        return

    uv_bin = shutil.which("uv")
    if uv_bin:
        res = subprocess.run(  # noqa: S603
            [uv_bin, "lock", "--offline"],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return

    raw = lock_path.read_text(encoding="utf-8")
    parts = re.split(r"(?=^\[\[package\]\]\n)", raw, flags=re.MULTILINE)
    if len(parts) <= 1:
        return
    header, pkg_blocks = parts[0], parts[1:]
    updated: list[tuple[str, str]] = []
    for block in pkg_blocks:
        if 'name = "template-mcp"\n' in block and 'source = { editable = "." }' in block:
            block = block.replace('name = "template-mcp"\n', f'name = "{name}"\n', 1)
        m = re.search(r'^name = "([^"]+)"', block, flags=re.MULTILINE)
        pkg_name = m.group(1) if m else ""
        updated.append((pkg_name, block))
    updated.sort(key=lambda item: item[0])
    lock_path.write_text(header + "".join(b for _, b in updated), encoding="utf-8")


def stamp_k8s_and_workflow_placeholders(target_dir: Path, name: str, prefix: str) -> None:
    candidates: list[Path] = [target_dir / ".github" / "workflows" / "security-scan.yml"]
    k8s_dir = target_dir / "k8s"
    if k8s_dir.is_dir():
        for ext in ("*.yml", "*.yaml"):
            candidates.extend(k8s_dir.rglob(ext))

    for fpath in candidates:
        if not fpath.is_file() or fpath.is_symlink():
            continue
        raw = fpath.read_text(encoding="utf-8")
        protected = raw.replace("            - name: APP_NAME\n", "__SENTINEL_ENV_KEY_01__\n")
        protected = protected.replace("-e APP_NAME=", "__SENTINEL_ENV_FLAG_02__")
        protected = protected.replace("/mcp/template-mcp/v1", prefix)
        protected = protected.replace("APP_PATH_PREFIX", prefix)
        protected = protected.replace("APP_NAME", name)
        protected = protected.replace("template-mcp", name)
        protected = protected.replace("__SENTINEL_ENV_KEY_01__\n", "            - name: APP_NAME\n")
        protected = protected.replace("__SENTINEL_ENV_FLAG_02__", "-e APP_NAME=")
        fpath.write_text(protected, encoding="utf-8")


def _build_initial_profile(
    ctl: Any,
    args: argparse.Namespace,
    *,
    name: str,
    prefix: str,
    secrets_list: list[str],
    preset_override: str | None = None,
) -> dict[str, Any]:
    preset_name = preset_override or args.preset
    if preset_name:
        preset_def = ctl.PRESETS[preset_name]
        packs = ctl.normalize_packs(preset_def["packs"])
        infra = ctl.normalize_infra(str(preset_def.get("infra", "sym-professional-services")))
    else:
        packs = ctl.default_packs_dict()
        infra = "sym-professional-services"

    if args.infra is not None:
        infra = ctl.normalize_infra(args.infra)
    if args.a2ui:
        packs["a2ui"] = True
    if args.auth is not None:
        packs["auth"] = args.auth
    if args.db is not None:
        packs["db"] = args.db
    if args.type is not None:
        raw_type = args.type
        if raw_type in ("rest-adapter", "proxy"):
            if "rest" not in packs["adapters"]:
                packs["adapters"].append("rest")
        elif raw_type == "mcp-bridge":
            if "mcp-bridge" not in packs["adapters"]:
                packs["adapters"].append("mcp-bridge")
        elif raw_type == "direct" and not preset_name:
            packs["adapters"] = []
    if args.symphony_room is not None:
        packs["symphony_room"] = args.symphony_room
    if args.redis:
        packs["redis"] = True
    if args.scheduler:
        packs["scheduler"] = True
    if args.metrics:
        packs["metrics"] = True
    if args.otel:
        packs["metrics"] = True
        packs["otel"] = True

    return {
        "name": name,
        "prefix": prefix,
        "infra": infra,
        "packs": ctl.normalize_packs(packs),
        "secrets": secrets_list,
    }


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    target_dir = Path(args.target)

    if args.sync_core:
        template_dir, cleanup_temp = resolve_template_source(args.template_dir)
        try:
            ctl = _load_mcp_ctl_module(template_dir)
            rc = ctl.cmd_sync_core(target_dir.resolve(), str(template_dir), force=bool(args.force))
            sys.exit(rc)
        finally:
            if cleanup_temp:
                shutil.rmtree(template_dir, ignore_errors=True)

    # Validate --name before cloning or copying files so invalid slugs fail fast with exit code 2
    if args.name is not None:
        raw_check = args.name.lower().strip()
        if not NAME_PATTERN.fullmatch(raw_check):
            sys.stderr.write(
                f"Error: Invalid --name '{args.name}'. Must match ^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9]))*$ "
                "(PEP 508 lowercase alphanumeric characters and single non-trailing hyphens).\n"
            )
            sys.exit(2)

    if args.secrets:
        for raw_sec in args.secrets.split(","):
            cleaned_sec = raw_sec.strip()
            if cleaned_sec and not SECRET_KEY_PATTERN.fullmatch(cleaned_sec):
                sys.stderr.write(f"Error: Invalid secret key '{cleaned_sec}'. Must match ^[A-Z][A-Z0-9_]*$.\n")
                sys.exit(2)

    wants_a2ui = bool(args.a2ui) or (args.preset in ("interactive-app", "enterprise-ha"))
    template_dir, cleanup_temp = resolve_template_source(args.template_dir, require_a2ui=wants_a2ui)
    try:
        ctl = _load_mcp_ctl_module(template_dir)

        preset_override: str | None = None
        if args.name is None:
            cfg = prompt_interactive(ctl)
            name = cfg["name"]
            prefix = cfg["prefix"]
            preset_override = cfg["preset"]
            target_dir = Path(cfg["target"])
            secrets_raw = cfg["secrets_raw"]
            if preset_override in ("interactive-app", "enterprise-ha") and not (
                template_dir / "src" / "extensions" / "a2ui"
            ).is_dir():
                sys.stderr.write(
                    f"Error: Template directory does not contain A2UI extension assets: {template_dir}\n"
                )
                sys.exit(1)
        else:
            name = args.name.lower().strip()
            prefix = ctl.normalize_prefix(args.prefix, name)
            secrets_raw = args.secrets or ""

        secrets_list: list[str] = []
        for raw_sec in secrets_raw.split(","):
            cleaned_sec = raw_sec.strip()
            if cleaned_sec and cleaned_sec not in secrets_list:
                secrets_list.append(cleaned_sec)

        copy_blueprint_files(template_dir, target_dir)
        update_pyproject_and_lockfile(target_dir, name)
        stamp_k8s_and_workflow_placeholders(target_dir, name, prefix)

        profile = _build_initial_profile(
            ctl,
            args,
            name=name,
            prefix=prefix,
            secrets_list=secrets_list,
            preset_override=preset_override,
        )
        manifest = {
            "schema_version": 2,
            "template_version": ctl.read_template_version(template_dir),
            "profile": profile,
            "managed_files": {},
            "pack_owned_files": {},
        }
        initial_force = {"a2ui"} if profile["packs"].get("a2ui") else None
        ctl.reconcile_project(target_dir, manifest, template_dir=template_dir, force_pack_keys=initial_force)

        packs = profile["packs"]
        infra = profile["infra"]
        sre_ns = f"psm-{ctl.derive_sre_short_slug(name)}-5079" if infra == "sre" else ""

        sys.stdout.write("\nScaffolding Completed Successfully!\n")
        sys.stdout.write("=========================================================\n")
        sys.stdout.write(f"Project Root:       {target_dir.resolve()}\n")
        sys.stdout.write(f"Server Name:        {name}\n")
        sys.stdout.write(f"HTTP Path Prefix:   {prefix}\n")
        sys.stdout.write(f"Inbound Auth:       {packs['auth']}\n")
        sys.stdout.write(f"Database Pack:      {packs['db']}\n")
        sys.stdout.write(f"Adapters:           {', '.join(packs['adapters']) if packs['adapters'] else 'direct'}\n")
        sys.stdout.write(f"A2UI Extension:     {'Enabled (--a2ui)' if packs['a2ui'] else 'Disabled (Headless)'}\n")
        sys.stdout.write(f"Target Infra:       {infra}" + (f" ({sre_ns})" if sre_ns else "") + "\n")
        sys.stdout.write("=========================================================\n")
    finally:
        if cleanup_temp:
            shutil.rmtree(template_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
