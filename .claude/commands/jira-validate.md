---
description: Validate an existing Jira ticket or draft payload against MSS Board 2236 compliance gates.
---

# /jira-validate

Run the `fde-jira-ticket-validate` skill against a target ticket key or file path: `$ARGUMENTS`.

## Instructions
1. Extract the ticket key (e.g. `MSS-1810`) or file path from `$ARGUMENTS`.
2. Run `python3 scripts/jira_ticket.py validate <KEY>` (or `python3 scripts/jira_ticket.py lint <FILE>`).
3. Report blocking deficiencies, improvement warnings, and present clarifying questions to remediate gaps.
