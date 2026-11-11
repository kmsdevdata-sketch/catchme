# catchme resources

GIFs, screenshots and raw reports captured while testing catchme end to end against five demo
stacks (`examples/demo-shop-*`). Every stack has the **same three planted bugs** (N+1 on the order
list, missing index on `orders.user_id`, lost-update race on stock) and was run with the same setup:

- App: ECS Fargate 0.5 vCPU / 1 GB · DB: RDS `db.t3.micro` (2 vCPU / 1 GB, max_connections 101)
- 1 ms app↔DB latency (Toxiproxy) · 1M orders / 2M order items / 1,000 users (seed 42)
- 50 seeded test accounts logging in through each app's real login API (bcrypt / scrypt / PBKDF2)
- Scenarios: order list 30 VUs × 30 s, product detail 30 VUs × 20 s, 100 simultaneous orders

Recorded on 2026-11-11, macOS, Docker Desktop (10 CPUs, 8 GB).

## Results

| Stack | All 3 bugs caught | Queries/request (before → after fix) | Order list p95 (before → after) | Race invariant | Holds up to |
|---|---|---:|---:|---|---:|
| Node.js + Prisma | ✅ | 60.9 → 3.0 | 1,295 → 113 ms | ❌ → ✅ | 12 concurrent |
| NestJS + TypeORM | ✅ | 62.9 → 2.0 | 1,591 → 196 ms | ❌ → ✅ | 17 concurrent |
| Spring Boot + JPA | ✅ | 62.2 → 2.0 | 6,158 → 1,400 ms (with warm-up: 1,260 → 496 ms) | ❌ → ✅ | 10 concurrent |
| Django | ✅ | 64.3 → 3.0 | 2,624 → 321 ms | ❌ → ✅ | 5 concurrent |
| FastAPI + SQLAlchemy | ✅ | 62.3 → 2.0 | 3,397 → 601 ms | ❌ → ✅ | 9 concurrent |

Findings beyond the planted bugs (not planted, found by catchme):

- **Django** opens a new DB connection per request (`CONN_MAX_AGE=0` default): ~1.0 new session per
  request on every scenario, 4× slower product detail than the other stacks.
- **JVM warm-up skews short runs on Spring.** These recordings used 20–30 s runs without warm-up; at
  0.5 vCPU the JIT compiler takes about half the CPU for the first minute. catchme now warms each run up
  (20 s on Spring by default). Re-measured with warm-up: fixed order list p95 **1,260 → 496 ms** (meets the
  500 ms target; the table above says 1,400 ms) and product detail **1,672 → 1,633 req/s** (≈ noise; without
  warm-up it looked like a −35% regression).
- **FastAPI** stays CPU-bound at 0.5 vCPU after the fix (app CPU ≈ 100% of its limit, p95 601 ms).
- **Local vs production profile (Prisma)**: order list p95 316 ms locally (passes the 500 ms target)
  vs 1,295 ms under the production profile (fails) — the gap catchme exists to show.
- Login cost differs a lot by hashing scheme at 0.5 vCPU: p95 ~0.4 s (Prisma/scrypt) to ~5 s (Spring/BCrypt, cold JVM).

Notes on accuracy: the breaking point varies about ±3 concurrent requests between runs of the same
setup (Prisma measured 9 and 12 on two runs), and results are approximations — see each report's
Limitations section.

## Files

Each stack folder has the same set (Prisma has extra feature demos):

| File | What it shows |
|---|---|
| `01-setup.gif` | `init` → `profile` → `gen` → `up` → limits in `docker stats` → password hash from the app container → `seed` |
| `02-load-report.gif` | `load` (auth, steady load, race) → `report` → summary |
| `03-report-summary.{en,ko}.png` | rendered report: verdict, findings, results, breaking-point table |
| `05-before-after.{en,ko}.png` (`07-` for Prisma) | `catchme verify` before/after table |
| `report-*.md` | the raw Markdown reports the screenshots were made from |

Prisma only:

| File | What it shows |
|---|---|
| `prisma/04-breakpoint.gif` | breaking-point search: doubling, then bisecting → "holds up to N concurrent requests" |
| `prisma/05-local-vs-prod.{en,ko}.png` | local baseline (no limits/latency) vs production profile |
| `prisma/06-verify.gif` | fix in a separate tree, re-measure with the same profile/seed/scenarios |
| `prisma/08-hook-regression.gif` | opt-in hook: after an edit to `schema.prisma`, quick check (22 s) flags queries/request 3.0 → 47.0 and exits 2 |

Suggested README hero: `prisma/02-load-report.gif` + `prisma/07-before-after.en.png`.

## Tools

- `_tools/record.sh` — records terminal GIFs with [vhs](https://github.com/charmbracelet/vhs)
- `_tools/shot_report.py` — renders a report (or selected sections) to PNG with headless Chrome (needs `markdown`, `Pillow`)
- `_tools/stack_flow.sh` — the full recorded flow used for the non-Prisma stacks

```bash
SPEED=3 TITLE="..." resources/_tools/record.sh out.gif examples/demo-shop-prisma "catchme load"
python resources/_tools/shot_report.py report.md out.png --sections "Summary,Results"
resources/_tools/stack_flow.sh fastapi "FastAPI + SQLAlchemy" "<hash command>" <fixed-copy-dir>
```
