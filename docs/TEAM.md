# TEAM.md

## Team Composition
Solo project. Aarush Duvvuri is the sole contributor (aarush@bu.edu).

## Roles
| Role | Owner |
|---|---|
| Sprint lead | Aarush (rotation N/A for a solo team) |
| Implementation, testing, documentation | Aarush |
| Code review | Self-review checklist + AI review (see below) |

## Cadence
- Work sessions: self-directed, targeting at least 10 hours per week.
- Progress check-ins: during EC 601 sessions.
- The GitHub board is updated at the end of every work session.

## Communication channel (one)
Email, to the instructor and TA. No other channels.

## Decisions
N/A (solo). Technical decisions are recorded in commit messages and the sprint docs for traceability. When an AI reviewer pushes back on a design choice and I keep my choice, the disagreement and my reason go in [AI-Review-Log.md](AI-Review-Log.md).

## How code gets in (from Sprint 2 on)
1. One branch per user story; no direct pushes to `main`.
2. One pull request per story. Before merging I check: `uv run pytest -q` passes, no secrets committed, docs updated, and the story's acceptance criteria are met.
3. For design-level changes, an AI model reviews the diff as a second reviewer, standing in for a teammate's review.

## Silence / Contingency
If I am blocked or will miss a sprint deadline, I notify the instructor within 24 hours with a revised timeline. There is no teammate to notify.

## Open items
- [ ] Instructor and TA added to the repo as collaborators
- [ ] Solo arrangement confirmed with the instructor, including how the code-review requirement is met
