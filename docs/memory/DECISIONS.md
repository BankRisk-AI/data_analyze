# Architectural and Workflow Decisions

Decisions shared across all AI coding agents.

## D001 — Shared cross-agent memory
- Status: Accepted
- Decision: Use portable Markdown files stored in Git.
- Reason: Claude Code, Codex, Gemini CLI and other agents must share project context.
- Location: `docs/memory/`

## D002 — Single source of shared instructions
- Status: Accepted
- Decision: `AGENTS.md` contains common agent rules.
- Agent-specific files remain short and reference shared instructions.
- Reason: Avoid duplicated rules and inconsistent behavior.

## D003 — Token efficiency
- Status: Accepted
- Decision: Load only the memory and source files relevant to the current task.
- Keep summaries concise and avoid repeating historical context.
- Reason: Reduce context consumption and unnecessary analysis.

## D004 — Automatic session memory updates
- Status: Accepted
- Decision: At the end of each work session, agents update `CURRENT.md`
  and append a concise session summary.
- Update `PROJECT.md` and `DECISIONS.md` only when durable facts or decisions change.
- Reason: Preserve continuity between agents and sessions.

## D005 — Local memory validation
- Status: Accepted
- Decision: Provide a Python standard-library script to validate memory files.
- Validation must not modify project files automatically.
- Reason: Detect missing sections and malformed memory structure safely.

## D006 — Single task prompt
- Status: Accepted
- Decision: Keep `.github/prompts/prompt.txt` as the only task prompt file.
- Do not create duplicate task prompts.
- Reason: Maintain one place for the user's active task instructions.

## D007 — Database test safety
- Status: Accepted
- Decision: `TEST_DATABASE_URL` must point exclusively to a disposable test database.
- Never run destructive test setup against production or important data.
- Reason: `tests/conftest.py` drops and recreates `public` and `staging`.

## D008 — Git safety
- Status: Accepted
- Decision: Agents must not commit or push unless explicitly requested.
- Reason: Keep version-control operations under user control.
