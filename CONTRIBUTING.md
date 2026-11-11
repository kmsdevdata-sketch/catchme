# Contributing to catchme

Thanks for helping. The most useful contributions right now:

- **Stack references** — a `skills/catchme/references/<stack>.md` for a stack we don't cover yet (Rails,
  Laravel, .NET, Rust, Elixir, Spring WebFlux, …): how the app gets its DB settings, pool defaults, the
  usual N+1 / race / index patterns and their fixes, and runtime gotchas. See `node-typeorm.md` for the shape.
- **A demo** for that stack in `examples/demo-shop-<stack>/` with the same three planted bugs (N+1 on the
  order list, no index on `orders.user_id`, read-check-write stock update) and a `FIXES.md`.
- **MySQL support** — the measurement layer reads PostgreSQL statistics today (`pg_stat_statements`, EXPLAIN,
  `pg_stat_activity`); MySQL needs `performance_schema` equivalents.
- **Bug reports** with the command you ran, the stack, and `.prod-parity/state/up.log` or the report.

## How the repo is laid out

```
skills/catchme/SKILL.md        what the agent reads — rules, tools, facts (keep it short)
skills/catchme/scripts/        catchme (bash wrapper) + Python (stdlib only) + SQL
skills/catchme/templates/      k6 scenarios, Dockerfile templates, example seed/plan/invariants
skills/catchme/references/     per-stack worked examples
examples/                      demo apps, each with ready .prod-parity/ inputs
resources/                     recorded GIFs, screenshots, reports (+ _tools to re-record)
docs/                          user guides (EN, KO, JA, ZH-CN)
```

Principles:

- **Deterministic work in scripts, judgment in the skill.** If two runs must produce comparable numbers, it
  belongs in a script. Choosing scenarios, data, invariants and fixes belongs to the agent.
- **Safety lives in code.** Anything that could reach a non-local system is checked in the scripts, not
  only described in SKILL.md.
- **Standard library only** for Python, Bash 3.2 compatible for the wrapper (macOS), Docker as the only
  hard dependency.

## Checking a change

```bash
bash -n skills/catchme/scripts/catchme
python3 -m py_compile skills/catchme/scripts/*.py
cd examples/demo-shop-fastapi && ../../skills/catchme/scripts/catchme all && ../../skills/catchme/scripts/catchme teardown
```

CI (`.github/workflows/e2e.yml`) runs the FastAPI demo (with and without Python on the host) and the Go +
Redis demo on Linux, and checks that the report finds the planted bugs. Please run one demo locally for
changes to the scripts, and keep the host quiet while it measures.

## Translations

`README.md` and `docs/getting-started.md` are canonical. Translations live next to them as
`README.<lang>.md` / `getting-started.<lang>.md` (`ko`, `ja`, `zh-CN`). If you change the English text,
a note in the PR is enough — translations can follow.
