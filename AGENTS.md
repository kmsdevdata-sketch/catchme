# catchme — instructions for coding agents

This repository is an agent skill pack, not an application. If you are an agent other than
Claude Code (Codex, Cursor, Gemini CLI, ...), use it like this:

1. Read `skills/catchme/SKILL.md` — the full workflow, safety rules and interpretation guide.
2. Run every step through the wrapper from the **target project's root**:

   ```bash
   /path/to/catchme/skills/catchme/scripts/catchme help
   ```

3. Read the stack reference that matches the project:
   `skills/catchme/references/{spring-jpa,node-prisma,node-typeorm,django,fastapi}.md`, plus `auth.md` for auth.

Requirements: Docker (with Compose v2). Python 3 and curl are used if available.

Safety summary (see SKILL.md for the full list):
- Local Docker only. Stop and ask if anything points at a non-local database.
- AWS lookups are read-only (`describe-*`/`list-*`) and need user consent. Never output credentials.
- Test accounts and test secrets only.
- Fixes go to a separate branch in a git worktree; never touch the user's current branch.

All generated files go under `<project>/.prod-parity/`.
