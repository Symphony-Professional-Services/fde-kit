---
description: Create a compliant Jira ticket (Epic or Story) on MSS Board 2236 with preflight schema validation.
---

# /jira-create

Run the `fde-jira-ticket-create` skill using the provided context or arguments.

## Instructions
1. Parse the user's prompt or arguments: `$ARGUMENTS`.
2. Determine the track:
   - **Client Engagement**: external customer, sponsor contact (`@symphony.com`), Confluence workspace link. Labels: `fde-engagement`, `<slug>`, `tier-1-anchor`, `stage-XX-name`.
   - **Self-Initiative / Internal Tooling**: developer tool, agent, CLI, or MCP server. Customer: `Internal / Symphony FDE`, internal owner. Labels: `self-initiative`, `fde-tooling`, `<slug>`, `tier-1-anchor`.
3. Assemble the payload and execute `python3 scripts/jira_ticket.py create --dry-run` to run the preflight compliance hook.
4. If the preflight hook passes, prompt the user for confirmation or execute the live creation.
5. If the user provided credentials or environment variables are set, create the ticket on Board 2236 and report the link.
