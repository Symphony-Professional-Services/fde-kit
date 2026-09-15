#!/usr/bin/env python3
"""
Jira Ticket Automation Script for Market Solutions Services (MSS)
Enforces structured format, FDE taxonomy, custom fields, and validation for Board 2236.
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# Shared environment loader from sync_confluence
REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> Dict[str, str]:
    """Load configuration from .env in repo root or fallback to ai-docs."""
    env: Dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")

    ai_docs_path = Path(env.get("AI_DOCS_REPO_PATH", "/Users/sean.koval@symphony.com/repos/work/tools/ai-docs"))
    if ai_docs_path.exists():
        env_key_file = ai_docs_path / ".env.key"
        if env_key_file.exists():
            for line in env_key_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def get_jira_auth_header(
    oauth_token: Optional[str] = None,
    api_token: Optional[str] = None,
    email: Optional[str] = None,
) -> str:
    """Resolve authorization header from OAuth 2.0 Bearer token, API Key Basic Auth, or environment."""
    env = load_env()

    # 1. Explicit CLI arguments
    if oauth_token:
        token = oauth_token.strip()
        return token if token.lower().startswith("bearer ") else f"Bearer {token}"
    if api_token and email:
        encoded = base64.b64encode(f"{email.strip()}:{api_token.strip()}".encode()).decode()
        return f"Basic {encoded}"

    # 2. Jira-specific OAuth token
    jira_oauth = (
        os.environ.get("JIRA_OAUTH_TOKEN")
        or os.environ.get("ATLASSIAN_OAUTH_TOKEN")
        or env.get("JIRA_OAUTH_TOKEN")
        or env.get("ATLASSIAN_OAUTH_TOKEN")
        or env.get("OAUTH_ACCESS_TOKEN")
    )
    if jira_oauth:
        token = jira_oauth.strip()
        return token if token.lower().startswith("bearer ") else f"Bearer {token}"

    # 3. Jira-specific API Key / Basic Auth
    jira_email = (
        os.environ.get("JIRA_USER_EMAIL")
        or env.get("JIRA_USER_EMAIL")
        or os.environ.get("ATLASSIAN_USER_EMAIL")
        or env.get("ATLASSIAN_USER_EMAIL")
    )
    jira_token = (
        os.environ.get("JIRA_API_TOKEN")
        or env.get("JIRA_API_TOKEN")
        or os.environ.get("ATLASSIAN_API_TOKEN")
        or env.get("ATLASSIAN_API_TOKEN")
    )
    if jira_email and jira_token:
        encoded = base64.b64encode(f"{jira_email.strip()}:{jira_token.strip()}".encode()).decode()
        return f"Basic {encoded}"

    # 4. Jira-specific Raw Header / B64
    jira_raw = env.get("JIRA_AUTHORIZATION_HEADER") or env.get("JIRA_BASIC_AUTH_B64")
    if jira_raw:
        val = jira_raw.strip()
        return val if val.lower().startswith("basic ") or val.lower().startswith("bearer ") else f"Basic {val}"

    # 5. Fallback to Confluence credentials if Jira-specific ones are not set
    conf_email = os.environ.get("CONFLUENCE_EMAIL") or env.get("CONFLUENCE_EMAIL")
    conf_token = os.environ.get("CONFLUENCE_API_TOKEN") or env.get("CONFLUENCE_API_TOKEN")
    if conf_email and conf_token:
        encoded = base64.b64encode(f"{conf_email.strip()}:{conf_token.strip()}".encode()).decode()
        return f"Basic {encoded}"

    conf_raw = env.get("CONFLUENCE_AUTHORIZATION_HEADER") or env.get("CONFLUENCE_BASIC_AUTH_B64")
    if conf_raw:
        val = conf_raw.strip()
        return val if val.lower().startswith("basic ") or val.lower().startswith("bearer ") else f"Basic {val}"

    print(
        "ERROR: No valid Jira credentials found. Provide either:\n"
        "  - Generated API Key: pass --api-token <KEY> --email <EMAIL> or set JIRA_API_TOKEN and JIRA_USER_EMAIL\n"
        "  - OAuth 2.0 Bearer: pass --oauth-token <TOKEN> or set JIRA_OAUTH_TOKEN",
        file=sys.stderr,
    )
    sys.exit(1)


DEFAULT_JIRA_BASE_URL = "https://perzoinc.atlassian.net/rest/api/3"


# MSS Custom Field Mappings
WORKSTREAM_MAP = {
    "Voice & Cloud9 Solutions": "36515",
    "AI, RAG & NL Querying": "36512",
    "Task Automation Bots": "36513",
    "Federation & Relays": "36514",
    "Enhanced Directory Solutions": "36566",
    "Platform Compliance & Alerts": "36516",
    "Client Data Operations": "36517",
    "Symphony Data Extraction": "36561",
    "SaaS Integrations": "36562",
    "Client System Adapters": "36563",
    "Core Infra & Ops": "36564",
    "DART": "40238",
}

ENGAGEMENT_TYPE_MAP = {
    "New Implementation": "36494",
    "Renewal / Upsell": "36495",
    "Maintenance / Support": "36496",
    "POC / Pre-Sales": "36497",
    "Partnership / Integration": "40239",
}

TSHIRT_MAP = {
    "XS": "11004",
    "S": "11003",
    "M": "11002",
    "L": "11001",
    "XL": "11000",
    "XXL": "25840",
}


def build_adf_description(
    overview: str,
    primary_ask: List[str],
    commercial_path: str,
    contacts: List[str],
    links: List[str],
    acceptance_criteria: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Builds standard Atlassian Document Format (ADF) for MSS tickets."""
    content: List[Dict[str, Any]] = []

    # Overview
    content.append({"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Overview"}]})
    content.append({"type": "paragraph", "content": [{"type": "text", "text": overview}]})

    # Primary Ask & Scope
    content.append({"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Primary Ask & Scope"}]})
    items = []
    for item in primary_ask:
        items.append({"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": item}]}]})
    content.append({"type": "bulletList", "content": items})

    # Commercial & Delivery Path
    content.append({"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Commercial & Delivery Path"}]})
    content.append({"type": "paragraph", "content": [{"type": "text", "text": commercial_path}]})

    # Key Contacts
    content.append({"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Key Contacts"}]})
    contact_items = []
    for contact in contacts:
        contact_items.append({"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": contact}]}]})
    content.append({"type": "bulletList", "content": contact_items})

    # Authoritative Links
    content.append({"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Authoritative Links"}]})
    link_items = []
    for link in links:
        link_items.append({"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": link}]}]})
    content.append({"type": "bulletList", "content": link_items})

    # Acceptance Criteria (if provided)
    if acceptance_criteria:
        content.append({"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Acceptance & Stage Exit Criteria"}]})
        ac_items = []
        for ac in acceptance_criteria:
            ac_items.append({"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": ac}]}]})
        content.append({"type": "bulletList", "content": ac_items})

    return {"type": "doc", "version": 1, "content": content}


def preflight_check(payload: Dict[str, Any]) -> tuple[bool, List[str], List[str]]:
    """Programmatic compliance gate. Validates payload against MSS Board 2236 standards."""
    import re

    fields = payload.get("fields", {})
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Project & IssueType
    if fields.get("project", {}).get("key") != "MSS":
        errors.append("Project must be 'MSS'.")
    if not fields.get("issuetype", {}).get("id"):
        errors.append("Missing issuetype ID.")

    # 2. Summary format [Prefix] Title
    summary = fields.get("summary", "")
    if not re.match(r"^\[[a-zA-Z0-9_ -]+\]\s.+$", summary):
        errors.append(f"Summary '{summary}' must follow standard prefix format: `[Engagement-Slug] Meaningful Title`.")

    # 3. Taxonomy & Track Verification
    labels = fields.get("labels", [])
    has_client_track = "fde-engagement" in labels
    has_self_track = "self-initiative" in labels

    if not has_client_track and not has_self_track:
        errors.append("Must contain either 'fde-engagement' (client track) or 'self-initiative' (internal tooling track) in labels.")
    elif has_client_track and has_self_track:
        warnings.append("Both 'fde-engagement' and 'self-initiative' labels present; choose one primary track.")

    # 4. Custom fields
    if not fields.get("customfield_19146"):
        errors.append("Missing custom field: Solution Workstream (`customfield_19146`).")
    if not fields.get("customfield_19140"):
        errors.append("Missing custom field: Engagement Type (`customfield_19140`).")
    if not fields.get("customfield_12201"):
        errors.append("Missing custom field: T-Shirt Size (`customfield_12201`). Flagged by Board 2236.")
    if not fields.get("customfield_13100"):
        errors.append("Missing customer/unit (`customfield_13100`).")

    # 5. Track-specific checks
    if has_self_track:
        cust = str(fields.get("customfield_13100", ""))
        if not any(cust.lower().startswith(p) for p in ["internal", "symphony fde", "self"]):
            warnings.append(f"Customer '{cust}' for self-initiative should typically indicate internal (e.g. 'Internal / Symphony FDE').")

    # 6. Description ADF structure
    desc = fields.get("description", {})
    if not isinstance(desc, dict) or desc.get("type") != "doc":
        errors.append("Description must be a valid Atlassian Document Format (ADF) document with type='doc'.")
    else:
        headings = []
        for item in desc.get("content", []):
            if item.get("type") == "heading":
                for text_node in item.get("content", []):
                    headings.append(text_node.get("text", "").lower())

        required_headings = ["overview", "primary ask", "contacts", "links"]
        for rh in required_headings:
            if not any(rh in h for h in headings):
                errors.append(f"Description missing mandatory ADF section heading: '{rh.title()}'.")

    return (len(errors) == 0, errors, warnings)


def create_issue(
    project_key: str,
    issue_type: str,
    summary: str,
    description_adf: Dict[str, Any],
    labels: List[str],
    workstream: Optional[str] = None,
    engagement_type: Optional[str] = None,
    tshirt: Optional[str] = None,
    customer: Optional[str] = None,
    base_url: Optional[str] = None,
    oauth_token: Optional[str] = None,
    api_token: Optional[str] = None,
    email: Optional[str] = None,
    dry_run: bool = False,
    skip_hook: bool = False,
) -> Dict[str, Any]:
    """Creates an issue in Jira MSS."""
    # Type ID mapping
    type_ids = {"Initiative": "10501", "Epic": "6", "Story": "7", "Sub-task": "5"}
    type_id = type_ids.get(issue_type, "6")

    fields: Dict[str, Any] = {
        "project": {"key": project_key},
        "issuetype": {"id": type_id},
        "summary": summary,
        "description": description_adf,
        "labels": labels,
    }

    if workstream and workstream in WORKSTREAM_MAP:
        fields["customfield_19146"] = {"id": WORKSTREAM_MAP[workstream]}
    if engagement_type and engagement_type in ENGAGEMENT_TYPE_MAP:
        fields["customfield_19140"] = {"id": ENGAGEMENT_TYPE_MAP[engagement_type]}
    if tshirt and tshirt in TSHIRT_MAP:
        fields["customfield_12201"] = {"id": TSHIRT_MAP[tshirt]}
    if customer:
        fields["customfield_13100"] = customer

    payload = {"fields": fields}

    # Run Pre-Flight Compliance Hook
    if not skip_hook:
        is_valid, errors, warnings = preflight_check(payload)
        for w in warnings:
            print(f"⚠️  [PREFLIGHT WARNING] {w}", file=sys.stderr)
        if not is_valid:
            print("\n❌ PREFLIGHT COMPLIANCE HOOK FAILED:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            print("\nAborting ticket submission. Fix the above deficiencies before creating.", file=sys.stderr)
            sys.exit(1)
        print("✅ Preflight compliance check PASSED.")

    if dry_run:
        print("[DRY RUN] Would create issue with payload:")
        print(json.dumps(payload, indent=2))
        return {"dry_run": True, "payload": payload}

    auth_hdr = get_jira_auth_header(oauth_token=oauth_token, api_token=api_token, email=email)

    endpoint_base = base_url or os.environ.get("JIRA_BASE_URL") or DEFAULT_JIRA_BASE_URL
    req = urllib.request.Request(
        f"{endpoint_base}/issue",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": auth_hdr, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"SUCCESS: Created {data.get('key')} -> https://perzoinc.atlassian.net/browse/{data.get('key')}")
            return data
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        print(f"HTTP Error {e.code}: {error_msg}", file=sys.stderr)
        sys.exit(1)


def get_issue(
    issue_key: str,
    base_url: Optional[str] = None,
    oauth_token: Optional[str] = None,
    api_token: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetches full issue details from Jira."""
    auth_hdr = get_jira_auth_header(oauth_token=oauth_token, api_token=api_token, email=email)
    endpoint_base = base_url or os.environ.get("JIRA_BASE_URL") or DEFAULT_JIRA_BASE_URL
    req = urllib.request.Request(
        f"{endpoint_base}/issue/{issue_key}",
        headers={"Authorization": auth_hdr, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode('utf-8')}", file=sys.stderr)
        sys.exit(1)


def validate_issue(
    issue_key: str,
    base_url: Optional[str] = None,
    oauth_token: Optional[str] = None,
    api_token: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Validates an existing ticket against FDE quality standards."""
    data = get_issue(issue_key, base_url=base_url, oauth_token=oauth_token, api_token=api_token, email=email)
    fields = data.get("fields", {})

    findings: List[str] = []
    warnings: List[str] = []

    # 1. Check Summary
    summary = fields.get("summary", "")
    if not summary.startswith("[") or "]" not in summary:
        warnings.append("Summary does not follow standard tag prefix `[Engagement] Title` format.")

    # 2. Check Labels
    labels = fields.get("labels", [])
    if "fde-engagement" not in labels:
        findings.append("Missing required label `fde-engagement`.")
    if not any(l.startswith("stage-") for l in labels):
        warnings.append("Missing lifecycle stage label (e.g. `stage-01-discover`).")

    # 3. Check Workstream & Engagement Type
    workstream = fields.get("customfield_19146")
    if not workstream:
        findings.append("Missing custom field: Solution Workstream.")

    tshirt = fields.get("customfield_12201")
    if not tshirt:
        warnings.append("Missing custom field: T-Shirt Size (flagged on board).")

    # 4. Check Description ADF structure
    desc = fields.get("description")
    if not desc:
        findings.append("Description is empty.")
    else:
        headings = []
        for item in desc.get("content", []):
            if item.get("type") == "heading":
                for text_node in item.get("content", []):
                    headings.append(text_node.get("text", "").lower())

        required_headings = ["overview", "primary ask", "contacts", "links"]
        for rh in required_headings:
            if not any(rh in h for h in headings):
                findings.append(f"Description missing standard section heading: '{rh.title()}'.")

    status = fields.get("status", {}).get("name")
    assignee = fields.get("assignee", {}).get("displayName") if fields.get("assignee") else "Unassigned"

    result = {
        "key": issue_key,
        "summary": summary,
        "status": status,
        "assignee": assignee,
        "valid": len(findings) == 0,
        "findings": findings,
        "warnings": warnings,
    }

    print(f"=== FDE Quality Audit for {issue_key} ===")
    print(f"Summary:  {summary}")
    print(f"Status:   {status}")
    print(f"Assignee: {assignee}")
    print(f"Labels:   {labels}")
    print(f"Result:   {'PASS' if result['valid'] else 'FAIL'}")

    if findings:
        print("\nBlocking Deficiencies:")
        for f in findings:
            print(f"  ❌ {f}")
    if warnings:
        print("\nImprovement Warnings:")
        for w in warnings:
            print(f"  ⚠️  {w}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jira MSS Ticket Automation")
    parser.add_argument("--oauth-token", help="OAuth 2.0 Bearer access token")
    parser.add_argument("--api-token", help="Atlassian API token")
    parser.add_argument("--email", help="Atlassian user email (used with --api-token)")
    parser.add_argument("--base-url", help="Jira REST API base URL override")

    subparsers = parser.add_subparsers(dest="command")

    # create
    create_p = subparsers.add_parser("create")
    create_p.add_argument("--project", default="MSS", help="Jira Project Key")
    create_p.add_argument("--type", default="Epic", choices=["Epic", "Story", "Sub-task", "Initiative"])
    create_p.add_argument("--summary", required=True, help="Ticket summary/title")
    create_p.add_argument("--overview", required=True, help="Overview paragraph")
    create_p.add_argument("--ask", nargs="+", required=True, help="List of primary ask bullet points")
    create_p.add_argument("--commercial", required=True, help="Commercial/delivery path description")
    create_p.add_argument("--contacts", nargs="+", required=True, help="Key contacts list")
    create_p.add_argument("--links", nargs="+", required=True, help="Authoritative links")
    create_p.add_argument("--ac", nargs="*", help="Acceptance criteria list")
    create_p.add_argument("--labels", nargs="+", default=["fde-engagement"], help="Labels")
    create_p.add_argument("--workstream", default="Voice & Cloud9 Solutions", choices=list(WORKSTREAM_MAP.keys()))
    create_p.add_argument("--engagement-type", default="New Implementation", choices=list(ENGAGEMENT_TYPE_MAP.keys()))
    create_p.add_argument("--tshirt", default="L", choices=list(TSHIRT_MAP.keys()))
    create_p.add_argument("--customer", default="Cloud9 ProServ / Symphony FDE")
    create_p.add_argument("--dry-run", action="store_true", help="Preview payload without calling API")
    create_p.add_argument("--skip-hook", action="store_true", help="Skip preflight compliance hook")

    # validate
    val_p = subparsers.add_parser("validate")
    val_p.add_argument("key", help="Jira issue key (e.g. MSS-1810)")

    # lint
    lint_p = subparsers.add_parser("lint")
    lint_p.add_argument("file", help="Path to JSON payload file to validate against preflight hook")

    args = parser.parse_args()

    if args.command == "create":
        adf = build_adf_description(
            overview=args.overview,
            primary_ask=args.ask,
            commercial_path=args.commercial,
            contacts=args.contacts,
            links=args.links,
            acceptance_criteria=args.ac,
        )
        create_issue(
            project_key=args.project,
            issue_type=args.type,
            summary=args.summary,
            description_adf=adf,
            labels=args.labels,
            workstream=args.workstream,
            engagement_type=args.engagement_type,
            tshirt=args.tshirt,
            customer=args.customer,
            base_url=args.base_url,
            oauth_token=args.oauth_token,
            api_token=args.api_token,
            email=args.email,
            dry_run=args.dry_run,
            skip_hook=args.skip_hook,
        )
    elif args.command == "validate":
        validate_issue(
            args.key,
            base_url=args.base_url,
            oauth_token=args.oauth_token,
            api_token=args.api_token,
            email=args.email,
        )
    elif args.command == "lint":
        path = Path(args.file)
        if not path.exists():
            print(f"Error: file not found '{args.file}'", file=sys.stderr)
            sys.exit(1)
        data = json.loads(path.read_text())
        is_valid, errors, warnings = preflight_check(data)
        for w in warnings:
            print(f"⚠️  [PREFLIGHT WARNING] {w}")
        if not is_valid:
            print("❌ PREFLIGHT COMPLIANCE HOOK FAILED:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)
        print(f"✅ Payload in '{args.file}' PASSED preflight compliance check.")
    else:
        parser.print_help()
