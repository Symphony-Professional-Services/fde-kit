---
name: fde-jira-ticket-validate
description: Use when validating a Jira ticket in MSS (Board 2236) for FDE engagement completeness and asking clarifying questions.
---

# FDE Jira Ticket Validation

Audit Jira tickets on board 2236 against FDE quality gates and prompt users for missing strategic fields.

## Use when

- Assessing an existing Jira Epic or Story before binding it to an AI-DLC engagement hub.
- Reviewing an incoming client request or ticket to identify missing evidence or specifications.
- Auditing board 2236 tickets for missing fields (`flag-missing-tshirt`, missing workstream, missing contacts).

## Obtain first

- Target ticket key (e.g. `MSS-1810`, `MSS-1880`).
- Access credentials: Generated API Key (`--api-token <KEY> --email <EMAIL>`) or OAuth 2.0 Bearer Token (`--oauth-token <TOKEN>` or `JIRA_OAUTH_TOKEN` in `.env`).
- Access to Jira Cloud API via `scripts/jira_ticket.py`.

## Procedure

1. **Audit Existing Ticket**: Run `python3 scripts/jira_ticket.py validate <KEY>` to inspect fields and description structure.
2. **Evaluate Quality Criteria**:
   - Summary format: Must match `[<Slug>] <Title>`.
   - Mandatory labels: Must include `fde-engagement` and a lifecycle stage label (`stage-XX-name`).
   - Custom fields: Must have `customfield_19146` (Solution Workstream) and `customfield_12201` (T-Shirt Size).
   - Core description sections: Verify presence of `Overview`, `Primary Ask & Scope`, `Key Contacts`, and `Authoritative Links`.
3. **Formulate Clarifying Questions**: For any failed checks, do not reject unilaterally. Group deficiencies into an interactive interview:
   - *Missing Sponsor/Lead*: "Who is the ProServ delivery sponsor and FDE lead for this ticket?"
   - *Missing Confluence Anchor*: "What is the Confluence root page URL for this engagement?"
   - *Missing Workstream*: "Which MSS workstream does this belong to (e.g. Voice & Cloud9 Solutions, AI RAG, DART)?"
   - *Missing Criteria*: "What are the concrete observable criteria for completing this milestone?"
4. **Present Audit Verdict**: Present a Markdown table summarizing each check status (PASS / FAIL / WARNING) along with the targeted questions.

## Output

An FDE ticket quality audit report detailing deficiencies, followed by specific clarifying questions to achieve 100% compliance.

## Rules

- Do not attempt to guess or invent missing stakeholder contacts.
- Differentiate between blocking deficiencies (missing `fde-engagement` label, missing scope) and non-blocking warnings (missing due date).
- Provide the exact CLI command or JSON patch to resolve identified deficiencies.

## Completion checks

- [ ] Audit script executed against target key.
- [ ] Deficiencies categorized into blocking vs warning.
- [ ] Clarifying questions generated for any missing fields.
