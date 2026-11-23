# AI Agent Instructions

## 1. Purpose
This file defines shared instructions for all AI coding agents working
on the EBA Analyst project.

The shared project memory is stored in `docs/memory/` using Markdown.
It must remain portable across Claude Code, Codex, Gemini CLI and other agents.

## 2. Before starting work
Read these files:
1. `AGENTS.md`
2. `docs/memory/PROJECT.md`
3. `docs/memory/CURRENT.md`

Read `docs/memory/DECISIONS.md` only when relevant to the task.
Read session notes only when additional historical context is needed.

## 3. Source of truth
- Source code and tests are authoritative for implementation details.
- `PROJECT.md` describes stable architecture and project conventions.
- `CURRENT.md` describes the latest known project state and next steps.
- `DECISIONS.md` records durable architectural and technical decisions.
- Session notes provide historical context, not current implementation truth.

Verify important assumptions against the actual code before changing it.
If memory conflicts with the code, trust the code and correct the memory.

## 4. Token efficiency and context management

Token efficiency is a project-wide priority.

### Context loading
- Never read the entire repository unless explicitly required.
- Never read all memory files or session history at startup.
- Start with `AGENTS.md`, `CURRENT.md` and only the relevant sections of `PROJECT.md`.
- Read `DECISIONS.md` only when a decision affects the current task.
- Read at most the latest relevant session note when historical context is necessary.
- Inspect only files directly related to the task and their dependencies.

### Tool usage
- Prefer targeted commands (`grep`, `find`, `sed`, `git diff`) over dumping entire files.
- Limit command output with line ranges, filters and `head`.
- Avoid repeating searches or inspections when results are already available.
- Do not print `.env`, credentials, tokens or other secrets.
- Do not run tests unrelated to the changes.

### Response efficiency
- Be concise and technical.
- Avoid repeating project context already documented in memory.
- Do not explain basic concepts unless requested.
- Report only relevant findings, changes, test results and blockers.
- Ask only when missing information blocks safe progress.

### Memory efficiency
- Keep `CURRENT.md` short and actionable (preferably under 100 lines).
- Keep `PROJECT.md` focused on stable facts (preferably under 200 lines).
- Avoid duplicating information between memory files.
- Session summaries should normally be 10–20 lines.
- Remove obsolete information when updating memory.
- Prefer references to file paths over copying source code.
- Store decisions once in `DECISIONS.md` and reference them elsewhere.

### Task execution
- Break large tasks into small, verifiable steps.
- Do not perform broad analysis when a targeted inspection is sufficient.
- Before expanding the scope, explain why additional context or work is necessary.

## 5. During work
- Inspect existing implementation before modifying it.
- Follow the current project architecture and conventions.
- Prefer small, focused and reusable changes.
- Add or update tests when appropriate.
- Do not modify unrelated files.
- Never expose secrets or `.env` contents.
- Never run destructive database operations without verifying the target.
- `TEST_DATABASE_URL` must point exclusively to a disposable test database.
- Do not commit or push unless explicitly requested.

## 6. At the end of each work session
Update shared memory automatically:

1. Update `docs/memory/CURRENT.md` with the verified current state
   and the next concrete step.
2. Add a concise session summary under `docs/memory/sessions/`.
3. Update `PROJECT.md` only when stable project facts change.
4. Update `DECISIONS.md` only when a durable decision is made.
5. Run `.venv/bin/python scripts/validate_memory.py` and resolve reported errors.

Do not invent completed work, test results or decisions.
Clearly distinguish verified facts from assumptions and pending work.

## 7. Session notes
Use filenames in this format:

`YYYY-MM-DD-short-description.md`

Keep each note concise:
- Goal
- Changes
- Verification
- Remaining work

## 8. Safety
Before executing database migrations, resets, deletion, bulk updates
or other potentially destructive operations:
- identify the target environment;
- inspect the affected resources;
- explain the impact;
- obtain confirmation when the operation could destroy user data.

## 9. Communication
Explain important changes clearly.
Prefer practical, incremental steps.
Report modified files, executed tests and remaining issues.
