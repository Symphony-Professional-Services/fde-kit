![FDE Kit — a practical learning center and field toolkit for AI implementation](assets/fde-kit-banner.svg)

# FDE Kit

FDE Kit is a practical learning center and field toolkit for AI Forward Deployed Engineers (FDEs): engineers who work alongside customers to turn operational problems into adopted, governed production systems built on frontier models. It helps people learn the role, build the technical and customer craft, navigate engagements, and apply artifacts in real work.

## Who this is for

- **Learners** who want to become an AI FDE, at a frontier-model company or on an enterprise AI team. Start with the [curriculum](learning/curriculum/README.md).
- **Practitioners** starting or running an engagement. Start with the [stage playbook](stages/README.md).
- Delivery leaders and adjacent partners who need a shared model of the work.

## Engagement lifecycle

Every engagement follows a common spine:

**Discover → Frame → Design → Build → Deploy → Enable → Expand**

The lifecycle is a guide, not a one-way conveyor belt. New evidence can require the team to revisit an earlier decision; the goal is learning and delivered value, not simply advancing a stage. See the [engagement lifecycle](learning/engagement-lifecycle.md) for the loop-back rules.

## Find the right kind of help

| Area | Use it to answer | What belongs there |
| --- | --- | --- |
| [Learning](learning/README.md) | What should I understand, and why does it matter? | Role, principles, lifecycle, system patterns, curriculum, glossary |
| [Stages](stages/README.md) | What should happen now? | Operational guidance for each lifecycle stage |
| [Skills](skills/README.md) | How do I perform a capability well? | Method, technical, and customer-craft guides that span stages |
| [Toolkit](toolkit/README.md) | What can I use right now? | Copy-ready field artifacts |
| [Examples](examples/README.md) | What does good FDE work look like? | A completed fictional engagement |
| [Agents](agents/README.md) | How does my agent harness run the method? | Agent skills that wrap the guides and templates |

## What is in the kit

- **Eleven skill guides.** Four method guides (workflow discovery, human/software/AI system design, evaluation and staged rollout, adoption and feedback), five technical guides (context engineering, tool-using agents, retrieval and grounding, grader design and error analysis, production readiness), and two customer-craft guides (discovery interviewing and facilitation, executive communication).
- **Thirteen toolkit artifacts.** From the discovery interview guide and stakeholder map, through the pilot charter, responsibility matrix, AI security review, evaluation pack, rollout plan, and operating plan, to the business case, executive readout, and field report.
- **[AI system patterns](learning/system-patterns.md)** with diagrams: assist; extract, validate, act; retrieval-grounded assistant; tool-using agent; batch classification and routing.
- **A seven-module [curriculum](learning/curriculum/README.md)** ending in a capstone engagement with a rubric, plus a [glossary](learning/glossary.md).
- **The [AI Implementation Field Playbook](learning/presentations/fde-overview.html)**, a 16-slide deck. GitHub displays HTML source, so clone the repository and open the file in a browser.
- **The [AI-assisted invoice-intake engagement](examples/invoice-intake-ai/README.md)**, a fictional worked example showing every stage and the seven original artifacts working together.
- **Six [agent skills](agents/README.md)** in the AI-DLC convention, so an FDE can run a workflow trace, opportunity scorecard, responsibility matrix, evaluation pack, security review, or field report from inside Claude Code, Codex, or a similar harness.

## Start here

### Learner path

1. Read [What is an FDE?](learning/what-is-an-fde.md), the [operating principles](learning/operating-principles.md), and the [engagement lifecycle](learning/engagement-lifecycle.md).
2. Work through the [curriculum](learning/curriculum/README.md) in order. Each module produces an artifact; the capstone runs a fictional engagement end to end.
3. Apply the capstone learnings to real-world customer engagements.

### Active-engagement path

1. Use the [engagement lifecycle](learning/engagement-lifecycle.md) to identify the current stage and its expected transition.
2. Open the [stage page](stages/README.md) for the current work and exit criteria; it names the guides and artifacts for that stage.
3. Apply the relevant [skill guide](skills/README.md) and copy the matching [toolkit artifact](toolkit/README.md), or run the matching [agent skill](agents/README.md) in your harness.
4. Choose the [system pattern](learning/system-patterns.md) that meets the outcome with the least autonomy, and complete the [AI security review](toolkit/ai-security-review.md) before Deploy.
5. Compare the evidence chain with the completed [invoice-intake example](examples/invoice-intake-ai/README.md), adapting its thresholds and boundaries to the engagement at hand.

### Stage playbook

1. [Discover](stages/01-discover/README.md)
2. [Frame](stages/02-frame/README.md)
3. [Design](stages/03-design/README.md)
4. [Build](stages/04-build/README.md)
5. [Deploy](stages/05-deploy/README.md)
6. [Enable](stages/06-enable/README.md)
7. [Expand](stages/07-expand/README.md)

## Team onboarding & fresh computer setup

The FDE toolkit is designed for engineers working across **macOS (Apple Silicon)**, **Ubuntu Linux**, and **Windows (via WSL2)**:

- **macOS (arm64)**: Native support via Homebrew and mise.
- **Ubuntu / Debian**: Native Linux support via `apt` and mise.
- **Windows**: Supported through **WSL2 (Ubuntu)**. Native Windows cmd/PowerShell is not supported; run `wsl --install -d Ubuntu` and execute the setup inside your WSL2 environment.

To enroll your machine into the team's FDE profile and install all toolchains in one step:

```sh
# Clone and run the onboarding script
git clone git@github.com:Symphony-Professional-Services/fde-kit.git
cd fde-kit
./scripts/setup-fde.sh
ai-dlc setup apply
```

## Agent harness & workflow rails

### 1. The Steering Rules (`AGENTS.md` and `.agents/rules/ai-dlc.md`)

Every time Antigravity or Claude Code starts a turn, these files instruct the agent:
- **Check current state** via `.ai-dlc/work/` and `ai-dlc.toml` before taking action.
- **Never invent** numbers, acceptance criteria, or customer credentials.
- **Keep durable explanations** in `docs/` and behavioral requirements in `openspec/`.
- **Complete work only** through `ai-dlc work finish` (which verifies tests, linters, and docs).

### 2. The Rails (Hard Enforcements)

- `ai-dlc project check --required`: Verifies links, schemas, formatting, types, and tests.
- `ai-dlc work start <id>` / `ai-dlc work finish <id>`: Prevents merging code into main unless associated tracker items, specifications, and evidence-based verification pass.
- **OpenSpec**: If modifying system behavior, the agent is blocked from writing code until an OpenSpec change (`proposal.md`, `specs/`, `tasks.md`) is recorded.

### 3. The Skills Map & Natural Language Triggers

Both Antigravity and Claude Code automatically index skills from `.agents/skills/` and `.claude/skills/`. The agent activates them based on natural language intent or explicit command:

| Engagement Phase | Tool / Skill | Natural Language Trigger Examples | What It Produces |
| :--- | :--- | :--- | :--- |
| **Kickoff / Day Start** | `day-start` | *"What should we work on today?"* / *"What is our project status?"* | Reads open work records, Jira tickets, and suggests next priority. |
| **Discovery & Scoping** | [`fde-workflow-trace`](agents/skills/fde-workflow-trace/SKILL.md) | *"Help me map this customer's manual invoice flow"* | Produces a baseline [`workflow-trace.md`](toolkit/workflow-trace.md) with steps, pain points, and times. |
| **Opportunity Triage** | [`fde-opportunity-scorecard`](agents/skills/fde-opportunity-scorecard/SKILL.md) | *"Score this client use case to see if it's viable for AI"* | Produces an [`opportunity-scorecard.md`](toolkit/opportunity-scorecard.md) (Advance, Defer, or Reject). |
| **Scoping & Boundaries** | [`fde-responsibility-matrix`](agents/skills/fde-responsibility-matrix/SKILL.md) | *"Define what the LLM does vs deterministic code vs human"* | Produces [`responsibility-matrix.md`](toolkit/responsibility-matrix.md) to prevent dangerous unbounded agents. |
| **Requirements & PRD** | `prd-draft` | *"Draft the PRD for this pilot engagement"* | Writes `docs/design/<feature>-prd.md` with measurable acceptance criteria. |
| **System Behavior** | `needs-spec` & `spec-from-prd` | *"Spec out the tool calling and data schemas"* | Creates `openspec/changes/<change-id>/` with exact behavior specs. |
| **QA, Evals & Graders** | [`fde-eval-pack`](agents/skills/fde-eval-pack/SKILL.md) | *"Build test cases and graders for our model output"* | Produces [`evaluation-pack.md`](toolkit/evaluation-pack.md) with assertion suites and baseline scores. |
| **Security & Governance** | [`fde-security-review`](agents/skills/fde-security-review/SKILL.md) | *"Prepare our security checklist for client review"* | Produces [`ai-security-review.md`](toolkit/ai-security-review.md) covering prompt injection, PII, and logging. |
| **Wrap-up & Day End** | `day-end` / `handoff` | *"Wrap up today's work"* / *"Prepare handoff for the team"* | Writes a handoff log in `.ai-dlc/work/` and updates ticket statuses. |

### 4. Where to Store Docs & What Syncs Where

To maintain consistency across projects, follow **The Triad**:

| Destination | What Lives Here | Authoritative Source For | Sync Mechanism |
| :--- | :--- | :--- | :--- |
| **Git Repository** (`docs/`, `openspec/`, `toolkit/`) | Technical specifications, code, eval sets, test scripts, security review, PRDs, ADRs. | **All Engineering & Behavior** | Single source of truth in git version control. |
| **Jira Cloud** | Task tickets, bugs, pilot milestones, delivery status (`To Do`, `In Progress`, `Done`). | **Status, Priority & Ownership** | AI-DLC links Git branch/commit directly to the Jira Issue ID. |
| **Confluence Space** | Executive Readouts, Pilot Charters, Stakeholder Memos, high-level client architecture overviews. | **Business Sponsors & Client Facing Stakeholders** | Markdown exported or pushed to Confluence via MCP / script upon release. |
| **Obsidian** (Local) | Daily personal notes, interview raw scratchpads, thought-logs. | **Individual Engineer Personal Journal** | Vault linked locally in `~/.config/ai-dlc/machines/`. Never checked into git. |

## Direction and contribution

The [roadmap](docs/roadmap.md) records what has shipped and what comes next; the [discovery review](docs/reviews/2026-09-07-fde-kit-review.md) records the evidence behind it. [CONTRIBUTING.md](CONTRIBUTING.md) states the quality bar, content conventions, required schemas, and the [AI-DLC](AI-DLC.md) workflow the repository uses. Every numeric rule in the kit is a starting heuristic, not an industry standard.
