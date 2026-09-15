---
name: fde-jira-ticket-create
description: Use when creating a structured FDE engagement Epic or Story in Jira project MSS (Board 2236).
---

# FDE Jira Ticket Creation

Create structured Tier 1 strategic engagement anchors and delivery milestones in Jira project `MSS` (Board 2236).

## Use when

- Anchoring a new customer engagement or internal FDE initiative to Jira project `MSS` (Market Solutions Services).
- Upgrading an unstructured idea or discovery interview into an authoritative business Epic.
- Creating stage-gated delivery stories with standard FDE taxonomy, custom fields, and required stakeholder links.

## Obtain first

Collect these required parameters before calling any tool or API:
- **Engagement Title & Slug**: Formatted as `[<Slug>] <Full Engagement Name>`.
- **Target Jira Issue Type**: `Epic` (for full engagement anchors) or `Story` (for delivery slices).
- **Solution Workstream**: One of the standard MSS options: `Voice & Cloud9 Solutions`, `AI, RAG & NL Querying`, `Task Automation Bots`, `Federation & Relays`, `Enhanced Directory Solutions`, `Platform Compliance & Alerts`, `Client Data Operations`, `DART`, `Core Infra & Ops`.
- **Engagement Type**: `New Implementation`, `POC / Pre-Sales`, `Renewal / Upsell`, `Maintenance / Support`, or `Partnership / Integration`.
- **T-Shirt Size**: Estimate (`XS`, `S`, `M`, `L`, `XL`, `XXL`).
- **Key Contacts**: Delivery sponsor and FDE lead (`@symphony.com` email addresses).
- **Authoritative Links**: Root Confluence page URL (`AIINT` space) and GitHub repository / Org Project board URL.
- **Measurable Acceptance Criteria**: Concrete observable outcomes for stage exit.

## Procedure

1. **Format Payload Content**: Structure the description in Atlassian Document Format (ADF) with explicit headings:
   - `Overview`: Business context and client problem statement.
   - `Primary Ask & Scope`: Key deliverables and architectural boundaries.
   - `Commercial & Delivery Path`: Sponsor, SOW milestone, and target deployment environment.
   - `Key Contacts`: Sponsor and FDE lead.
   - `Authoritative Links`: Confluence root and GitHub URLs.
   - `Acceptance & Stage Exit Criteria`: Bulleted verifiable assertions.
2. **Assign Taxonomy Labels**:
   - `fde-engagement` (mandatory)
   - `<slug>` (e.g. `c9-migration`, `osttra-dart`)
   - `tier-1-anchor` (for Epics)
   - `stage-<01-07>-<name>` (active lifecycle stage)
3. **Execute Dry Run**: Execute `python3 scripts/jira_ticket.py create --dry-run` to preview the JSON payload and verify field IDs.
4. **Submit Ticket**: Call `python3 scripts/jira_ticket.py create` without `--dry-run` to create the ticket.
5. **Bind Local Configuration**: Record the returned issue key (e.g. `MSS-1890`) in `ai-dlc.toml` under `[project.fde.jira_epic]` and update `docs/fde_engagements/<slug>/_index.md`.

## Output

A live Jira ticket in `MSS` with structured ADF description, custom field bindings, and standard labels, followed by the updated `ai-dlc.toml` binding.

## Rules

- Never submit tickets without `fde-engagement` label.
- Never invent stakeholder emails or Confluence page IDs. If unconfirmed, write `[gap: unconfirmed contact]`.
- Always set Solution Workstream and T-Shirt Size to avoid board flags (`flag-missing-tshirt`).

## Completion checks

- [ ] Jira ticket created and accessible on board 2236.
- [ ] Confluence and GitHub links resolve.
- [ ] Key recorded in `ai-dlc.toml` `jira_epic`.
