# Claude Code Instructions

Before starting:
1. Read `AGENTS.md`.
2. Read `docs/memory/CURRENT.md`.
3. Read only relevant sections of `docs/memory/PROJECT.md`.
4. Consult `docs/memory/DECISIONS.md` only when relevant.

Follow all shared rules in `AGENTS.md`.

Token efficiency:
- Do not load the full repository or session history.
- Inspect only files relevant to the task.
- Use targeted searches and limited command output.
- Reuse verified findings from the current conversation.
- Avoid repeating explanations and investigations.
- Keep responses concise.

At the end of each task, update shared memory as specified in `AGENTS.md`.
