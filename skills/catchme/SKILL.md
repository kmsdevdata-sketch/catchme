---
name: catchme
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/catchme *)
description: Reproduce production-like specs (CPU/memory limits, RDS instance class, app↔DB latency, production data volume) in local Docker, run k6 load and race scenarios, and report N+1 queries, connection-pool exhaustion, lock contention, missing indexes and race conditions with evidence. Use when the user asks to "test with production specs", "운영 사양으로 테스트해줘", load-test an API, check N+1 / race conditions / concurrency, find how many concurrent requests a spec can handle, or compare instance sizes (e.g. t3.micro vs t3.small). Works with any containerizable HTTP app on PostgreSQL, whatever the language or framework (verified on Spring JPA, Prisma, NestJS/TypeORM, Django, FastAPI and Go).
---

# catchme

Catch me if you can — before production does.

Local tests miss what production has: CPU limits, a small DB class, a millisecond per DB round
trip, and millions of rows. catchme rebuilds that in local Docker and measures it. The scripts make
the environment and the numbers reproducible; everything that needs judgment — what to test, how
much data, what an invariant is, what the numbers mean, what to fix — is yours. Treat what follows
as tools and facts, not a script to follow line by line.

## The tool

`${CLAUDE_SKILL_DIR}/scripts/catchme <command>`, run from the target project's root. Use that full
path every time (shell variables don't survive between commands; plugin variables aren't set in
your shell). Reference files write it as plain `catchme`. If `${CLAUDE_SKILL_DIR}` shows up
literally (an agent other than Claude Code), the script is `scripts/catchme` next to this file.
Needs Docker; uses Python 3 and curl if present.

| Command | What it does |
|---|---|
| `init` | detect stack (or generic), port, endpoints, auth, Dockerfile → `.prod-parity/project.json`; copies k6 scenarios |
| `profile ...` | production profile → `profile.yaml`. `--scan` / `--from-iac` (Terraform, CDK, ECS, k8s), `--aws ...` (read-only), `--app-preset ecs-fargate:0.5vcpu-1gb --db-preset rds:db.t3.micro`, `--list-presets`, `--latency-ms`, `--p95-ms`, `--cpu-mode burst\|baseline`, `--pool-size` |
| `gen`, `up [--baseline] [--with-oauth]`, `status`, `logs [svc]`, `exec <svc> <cmd>` | compose with limits + Toxiproxy latency; start, inspect, run things in containers |
| `seed [--force]` | generate data from `seed.yaml` against the migrated schema (skips if unchanged) |
| `load [--label L]` | run `plan.yaml`, collect everything into `runs/<label>/metrics.json` |
| `report [--label L] [--before L] [--lang ko]`, `report --analysis file.md` | Markdown report with findings, evidence, limitations; insert your analysis |
| `baseline` | same plan with no limits/latency (label `baseline`), then back to the profile |
| `breakpoint` | doubles VUs then bisects → "this spec holds up to N concurrent requests" |
| `verify <worktree>` | rebuild from a fix worktree, reseed, re-run the plan as `after`, before/after report |
| `quick`, `hooks on\|off` | 1-VU queries/request regression check used by the opt-in hook |
| `mint-tokens ...` | HS256 test JWTs for auth mode `token` |
| `teardown` | remove containers, volumes, image; keep `.prod-parity/` inputs and reports |

Everything generated lives in `<project>/.prod-parity/` and is meant to be read and edited.

**Any stack.** catchme measures from the outside — HTTP (k6), PostgreSQL statistics and EXPLAIN,
container resources — so it does not care what the app is written in. `init` has detectors for a
few stacks; anything else gets a generic profile (Dockerfile, `EXPOSE` port, common DB env vars:
`DATABASE_URL`, `DB_*`, `PG*`) and you fill in the rest from the code. The references are worked
examples, not a support list — for other stacks use what you know about them.

**Extending the environment.** `gen` always writes the same base (app, Postgres, Toxiproxy). Put
anything else the app needs — Redis, a queue, a mock of an external API, extra env, its own limits —
in `.prod-parity/compose.override.yml` (standard compose override syntax; `gen` never touches it).
Every catchme command picks it up and `teardown` removes it. Service names you add there count as
local hosts for the safety checks. Give added services production-like limits; they get no injected
latency (only app↔Postgres goes through Toxiproxy), so say that in the report. `init` warns when
the code seems to use Redis, a queue, Mongo, Elasticsearch or S3.

## Hard rules

These protect the user; they are not up for judgment.

1. Only local Docker. Never connect to, load or seed anything that isn't a catchme container. If
   config or `.env` points at a non-local DB (`detect` lists hosts in `warnings`), stop and ask.
2. AWS only read-only (`describe-*`/`list-*`) and only with the user's consent. Never print or
   store credentials or tokens; never create or change cloud resources.
3. Test accounts and test secrets only — never production users, keys or OAuth clients.
4. Never change the user's current branch. Code fixes go to a new branch in a git worktree.
5. Measure through the wrapper. You can read and edit anything it generates and run any extra
   diagnostics you like, but numbers you compare (before/after, local/prod) must come from the
   same `load`/`verify` path, otherwise the comparison means nothing.

## What you write

- **`project.json`** (after `init`) — fix what detection got wrong: `app.dockerfile` (if null,
  start from `${CLAUDE_SKILL_DIR}/templates/dockerfiles/<stack>.Dockerfile`), `app.env` for
  anything the app needs to boot (test values), `app.port`/`health_path`, `endpoints`, `query_file_globs`
  (used by the hook). PostgreSQL only for now — the measurement relies on its statistics.
- **`seed.yaml`** — row counts per table and SQL-expression `overrides` (`i` = row number) for
  columns with meaning: emails, status text, stock, prices, the test password hash. FK columns are
  filled automatically; unlisted parent tables get 100 rows. `exports` dump owner → ids maps for
  `{own:name}` paths. Example: `${CLAUDE_SKILL_DIR}/templates/config/seed.example.yaml`.
- **`plan.yaml`** — `base_url` (`http://app:<port>`), `auth`, and `runs`: `read.js` (constant
  VUs, `stages`, or `iterations`), `race.js` (N requests at the same instant), per-run `warmup`,
  `expected_status`, `invariants`, `quick`. Placeholders `{n}`, `{vu}`, `{iter}`, `{rand:a-b}`,
  `{own:name}`. Example: `${CLAUDE_SKILL_DIR}/templates/config/plan.example.yaml`.
- **`invariants.yaml`** — for writes to shared state: a `before` snapshot query and a `check`
  query returning `ok` (`{{snap}}` = the before row). The race verdict comes from these queries,
  not from status codes. Example: `${CLAUDE_SKILL_DIR}/templates/config/invariants.example.yaml`.
- **The Analysis section** of the report — your interpretation, tied to code (file:line). Write it
  to a file and run `report --analysis <file>`: it goes into the newest report and `latest.md`.
- Invariants run only for the runs that list them under `invariants:`.

Worked examples per stack (wiring, pool defaults, N+1/race/index patterns and fixes, gotchas) are in
`${CLAUDE_SKILL_DIR}/references/` — `spring-jpa.md`, `node-prisma.md`, `node-typeorm.md`,
`django.md`, `fastapi.md` — and auth in `auth.md`. Read the one that matches, if any.

## Worth knowing

- **Latency × query count** is the usual production-vs-local gap: an N+1 that costs nothing locally
  pays 1 ms per round trip under the profile. Explain mechanisms, not just numbers.
- **Two kinds of counter races.** Lost update (plenty of stock; after ≠ before − sold) and oversell
  (low stock; sold > stock). "No negative stock" catches neither when the code writes an absolute
  value. Mark correct rejections with `expected_status` so they aren't counted as errors.
- **Race runs change the data.** `verify` reseeds before measuring `after`; if you compare runs
  yourself, `seed --force` first.
- **Warm-up.** Each read run gets an unmeasured warm-up (default 20 s on Spring, 5 s elsewhere).
  At 0.5 vCPU a JVM can spend half its CPU JIT-compiling for the first minute, so short runs swing.
  Small differences on endpoints you didn't touch are usually noise; decide how far to chase them
  against what the user asked for, and report what you measured and what you ruled out.
- **Keep the host quiet while measuring.** Docker's CPU is shared: a build, test suite or another
  container running during `load`/`verify` skews the numbers (one such overlap made a fixed endpoint
  look 70% slower). Run builds and other heavy work before or after, not during.
- **Runtimes that size themselves from the CPU count see the laptop, not the limit.** Docker's
  `cpus` is a quota; `nproc` still reports every host core. Go < 1.25 (`GOMAXPROCS`, pgxpool's
  `NumCPU` default), Node `os.cpus()`, worker counts like `2 × cores + 1`, and many thread pools
  come out 5–10× larger locally than on a 0.5–2 vCPU task. Pin them in `app.env` to what production
  would get (the profile's `--pool-size` only fills the `{pool}` placeholder in `project.json → app.db_env`).
- **Pools are per process.** Gunicorn/uvicorn workers × pool size; Prisma/Node pool sizing ignores
  the CPU limit; Django opens a connection per request by default. The report flags ~1 new DB
  session per request.
- **The profile is an approximation** — CPU generation, disk IOPS, burst-credit depletion and real
  data distributions aren't modeled. The report adds a limitations table; mention anything
  specific to the run (assumed data volume, auth mode, replicas > 1).

## Working with the user

- If you don't know the production specs or data volume, ask — one question, with IaC/AWS/preset
  options (`profile --scan` first). If the user already gave them or said not to ask, go ahead and
  state every assumption at the top of the Analysis.
- Ask before changing code, unless the user already asked for fixes. Fix in a worktree branch, commit
  there, `verify`, and leave the branch for the user to review.
- A full run usually takes 10–15 minutes; the hook check under 2. `load` and `verify` each take
  a few minutes — give them a long timeout or run them in the background. Offer the slower extras
  (`baseline`, `breakpoint`, longer runs, `cpu-mode baseline`) instead of running them silently.
- Finish with a short summary in chat, the report path, and `teardown` (or ask whether to keep the
  environment up).

## Reading results

| Symptom | Likely cause | Evidence |
|---|---|---|
| queries/request ≫ 1 on a list endpoint; one SELECT ≈ k × requests | N+1 | statement, calls/request |
| p95 grows with VUs, active connections pinned at pool size, 5xx/timeouts | pool exhaustion | max active vs pool, status counts |
| lock waits, deadlocks, slow but correct writes | lock contention | lock_wait samples / log count, deadlocks |
| Seq Scan on a big table with a Filter | missing index | EXPLAIN node, rows, filter |
| ~1 new DB session per request | no connection pooling | new_sessions vs requests |
| app CPU ≈ 100% of its limit | CPU bound (ORM overhead, serialization, hashing) | CPU vs limit |
| invariant failed | race (lost update / check-then-act) | invariant detail row |
| memory near limit / OOMKilled | heap/runtime settings, unbounded result sets | mem max, OOM flag |
