---
name: fde-jira-ticket-create
description: Use when creating a structured FDE engagement Epic or Story in Jira project MSS (Board 2236).
---

# FDE Jira Ticket Creation

Create structured Tier 1 strategic engagement anchors and delivery milestones in Jira project `MSS` (Board 2236).

## Invocation Modes

- **Slash Command**: `/jira-create <context>` or `/fde-jira-ticket-create <context>`
- **Natural Language**: *"Create a Jira ticket for...", "Draft an Epic for our new MCP server..."*

## Use when

- Anchoring a new customer engagement or internal FDE initiative to Jira project `MSS` (Market Solutions Services).
- Upgrading an unstructured idea or discovery notes into an authoritative business Epic or Story.
- Creating stage-gated delivery stories with standard FDE taxonomy, custom fields, and required stakeholder links.

## Track Selection & Parameters

Select the appropriate track before assembling the ticket payload:

### Track A: Client Engagement (`labels: ['fde-engagement', ...]`)
- **Use when**: Client-facing project, external stakeholders, or formal ProServ sponsorship.
- **Required Labels**: `fde-engagement`, `<slug>`, `tier-1-anchor` (for Epics), `stage-XX-<name>`.
- **Customer**: External firm name (e.g. `Federal Reserve Bank of New York`, `National Bank of Canada`).
- **Contacts**: Delivery sponsor (`@symphony.com`) and FDE lead.
- **Links**: Root Confluence page (`AIINT` space) and GitHub repository.

### Track B: Self-Initiative / Tooling (`labels: ['self-initiative', 'fde-tooling', ...]`)
- **Use when**: Developer tools, CLI utilities, agent skills, MCP servers, or internal harness refinements.
- **Required Labels**: `self-initiative`, `fde-tooling`, `<slug>`, `tier-1-anchor`.
- **Customer**: `Internal / Symphony FDE` (or `Internal / Self`).
- **Contacts**: Tool lead / developer owner (`@symphony.com`).
- **Links**: Local repository path and GitHub repository URL.

## Common Parameters

- **Authentication Credentials**: Either a generated Atlassian API Token (`--api-token <KEY> --email <EMAIL>` or `JIRA_API_TOKEN`/`JIRA_USER_EMAIL` in `.env`) or an OAuth 2.0 Bearer Token (`--oauth-token <TOKEN>` or `JIRA_OAUTH_TOKEN` in `.env`).
- **Engagement Title & Slug**: Formatted as `[<Slug>] <Full Engagement Name>`.
- **Target Jira Issue Type**: `Epic` (for full anchors) or `Story` (for delivery slices).
- **Solution Workstream**: One of the standard MSS options: `Core Infra & Ops`, `Voice & Cloud9 Solutions`, `AI, RAG & NL Querying`, `Task Automation Bots`, `Federation & Relays`, `Enhanced Directory Solutions`, `Platform Compliance & Alerts`, `Client Data Operations`, `DART`.
- **Engagement Type**: `New Implementation`, `POC / Pre-Sales`, `Renewal / Upsell`, `Maintenance / Support`, or `Partnership / Integration`.
- **T-Shirt Size**: Estimate (`XS`, `S`, `M`, `L`, `XL`, `XXL`).
- **Acceptance Criteria**: Concrete observable criteria for completion.

## Procedure

1. **Format Payload Content**: Structure the description in Atlassian Document Format (ADF) with explicit headings:
   - `Overview`: Business context or developer motivation.
   - `Primary Ask & Scope`: Key deliverables and architectural boundaries.
   - `Commercial & Delivery Path`: Sponsor or developer lead and delivery milestones.
   - `Key Contacts`: Sponsor or owner contacts.
   - `Authoritative Links`: Confluence, GitHub, or local checkout links.
   - `Acceptance & Stage Exit Criteria`: Bulleted verifiable assertions.
2. **Execute Pre-Flight Compliance Hook**: Run `python3 scripts/jira_ticket.py create --dry-run` with your parameters. The built-in compliance hook will validate the payload against `toolkit/schemas/jira-ticket-schema.json`.
3. **Resolve Any Violations**: If the hook fails, remediate missing headings, missing fields, or incorrect prefixes before proceeding.
4. **Submit Ticket**: Call `python3 scripts/jira_ticket.py create` without `--dry-run` to post the ticket to Board 2236.
5. **Bind Local Configuration**: Record the returned issue key (e.g. `MSS-1890`) in `ai-dlc.toml` under `[project.fde.jira_epic]` or work records.

## Output

A live Jira ticket in `MSS` passing all preflight compliance gates, followed by updated local configuration binding.

## Rules

- Every ticket MUST contain either `fde-engagement` (Track A) or `self-initiative` (Track B).
- Always set Solution Workstream and T-Shirt Size to prevent board flags (`flag-missing-tshirt`).
- Never submit tickets without running the preflight compliance hook.

## Completion checks

- [ ] Preflight compliance hook reported `✅ PASSED`.
- [ ] Jira ticket created and accessible on board 2236.
- [ ] Authoritative links resolve.
- [ ] Issue key recorded in local configuration.
