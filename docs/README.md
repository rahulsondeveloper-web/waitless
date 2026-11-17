# WaitLess — Planning Documents

These documents are the pre-implementation deliverables required by Section 29 of the PRD ([#WAITLESS.md](../%23WAITLESS.md)). Implementation starts only after they are reviewed.

| # | Document | What it answers |
|---|---|---|
| 00 | [Decisions log](00-decisions.md) | Every choice made where the PRD was open, and why |
| 01 | [System architecture](01-system-architecture.md) | Components, runtime, tenancy, real-time, jobs, storage |
| 02 | [Database ER diagram](02-database-er.md) | Tables, relationships, integrity constraints |
| 03 | [Module dependencies](03-module-dependencies.md) | Backend and frontend module boundaries and which depends on which |
| 04 | [Roles & permissions](04-roles-permissions.md) | Role matrix, permission keys, plan feature gates |
| 05 | [User journeys](05-user-journeys.md) | Customer, Restaurant Admin and Super Admin flows |
| 06 | [API specification](06-api-specification.md) | REST endpoints, Socket.IO events, conventions |
| 07 | [Development plan](07-development-plan.md) | Phases, deliverables, acceptance tests, local setup |

Diagrams are written in Mermaid. VS Code shows them with the built-in Markdown preview (`Ctrl+Shift+V`) when the "Markdown Preview Mermaid Support" extension is installed; GitHub renders them natively.

- [08 — Security review](08-security-review.md)
- [09 — Deployment & operations](09-deployment.md)
- [10 — Load test](10-load-test.md)
