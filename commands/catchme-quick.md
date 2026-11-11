---
description: Quick queries-per-request regression check against the last full catchme run (environment must be up)
---

Read `${CLAUDE_PLUGIN_ROOT}/skills/catchme/SKILL.md` (the catchme skill), then run quick mode from the
project root: `${CLAUDE_PLUGIN_ROOT}/skills/catchme/scripts/catchme quick`.

- Exit 0: no regression — report the per-endpoint queries/request briefly.
- Exit 2: regression — show which endpoint grew, from what to what, and find the code change
  that introduced the extra queries.
- If the environment is not up or there is no baseline yet, say so and offer `/catchme`.

$ARGUMENTS
