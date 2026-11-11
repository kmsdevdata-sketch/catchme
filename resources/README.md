# catchme resources

GIFs, screenshots and raw reports from running catchme end to end against the demo stacks in
`examples/`. Every demo has the **same planted bugs** — N+1 on the order list, no index on
`orders.user_id`, and a stock update that loses writes (lost update) and oversells — and every run used
the same setup:

- App: ECS Fargate 0.5 vCPU / 1 GB · DB: RDS `db.t3.micro` (2 vCPU / 1 GB, max_connections 101)
- 1 ms app↔DB latency (Toxiproxy) · 1M orders / 2M order items / 1,000 users (seed 42)
- 50 test accounts logging in through each app's real login API (scrypt / bcrypt / PBKDF2)
- Scenarios: order list 30 VUs × 30 s and product detail 30 VUs × 20 s (each after a warm-up: 20 s on
  Spring, 5 s elsewhere), 100 simultaneous orders on a product with plenty of stock, 100 on a product with stock 10

Recorded 2026-11-11/12 on macOS / Docker Desktop (10 CPUs, 8 GB), catchme at the commit these files were added in.

## Results

| Stack | Bugs caught | Queries/request on the order list (before → after fix) | Order list p95 (before → after) | Lost update / oversell | Holds up to |
|---|---|---:|---:|---|---:|
| Node.js + Prisma | 3/3 | 61.0 → 3.0 | 1,677 → 110 ms | ❌❌ → ✅✅ | 13 concurrent |
| NestJS + TypeORM | 3/3 | 62.9 → 2.0 | 1,232 → 111 ms | ❌❌ → ✅✅ | 20 concurrent |
| Spring Boot + JPA | 3/3 | 62.1 → 2.0 | 1,175 → 512 ms | ❌❌ → ✅✅ | 13 concurrent |
| Django | 3/3 | 64.3 → 3.0 | 2,728 → 309 ms | ❌❌ → ✅✅ | 6 concurrent |
| FastAPI + SQLAlchemy | 3/3 | 61.7 → 2.0 | 2,050 → 497 ms | ❌❌ → ✅✅ | 10 concurrent |
| Go net/http + pgx + Redis ¹ | 3/3 | 81.4 → 2.0 | 1,966 → 47 ms | ❌❌ → ✅✅ | < 10 concurrent |

"Holds up to" = the breaking-point search on the order list before the fix (p95 ≤ 500 ms, errors ≤ 1%).

¹ No detector or reference for this stack: `init` used the generic profile, and the `.prod-parity/` files
(including Redis in `compose.override.yml` and `GOMAXPROCS=2` / `DB_MAX_CONNS=4`) were written by an agent
that had only the skill. Its plan starts the breaking-point search at 10, which already missed the target.

Local vs production profile (Prisma, same data and scenarios): order list p95 **323 ms locally** (passes
the 500 ms target) vs **1,287 ms under the production profile** (fails) — the gap catchme exists to show.

Found by catchme without being planted:

- **Django** opens a new DB connection per request (`CONN_MAX_AGE=0` default): ~1.0 new session per
  request on every scenario; product detail is 5× slower than on the other stacks.
- **FastAPI** and **Spring** are CPU-bound at 0.5 vCPU after the fix (app CPU ≈ 100% of its limit) —
  the remaining gap to 500 ms is sizing / serialization, not queries.
- The fixed code serializes concurrent orders on a row lock, so the 100-order race gets slower
  (e.g. Prisma 489 → 1,205 ms p95) while becoming correct. The report shows the lock waits.

How much to trust the numbers:

- **Run-to-run noise is real.** The breaking point moved by about ±3 concurrent requests between identical
  runs. On Spring at 0.5 vCPU the untouched product-detail endpoint measured −2% in one before/after run and
  −27% in another, even with warm-up — JIT and GC at half a CPU. Small differences are noise unless they repeat.
- **The host must be quiet.** One Spring run overlapped with an unrelated Docker build and showed the fixed
  order list at 996 ms and product detail 72% slower; re-run alone it was 512 ms. Results are approximations
  of production — see each report's Limitations section.

## Files

Per stack folder:

| File | What it shows |
|---|---|
| `01-setup.gif` | `init` → `profile` → `gen` → `up` → limits in `docker stats` → test password hash from the app container → `seed` (3M rows) |
| `02-load-report.gif` | `load` (auth, steady load, two races) → `report` → summary |
| `03-report-summary.{en,ko}.png` | rendered report: verdict, findings, results, breaking-point table |
| `05-before-after.{en,ko}.png` | `catchme verify`: before/after table from the fixed branch |
| `report-*.md` | the raw Markdown reports behind the screenshots |

Prisma also has:

| File | What it shows |
|---|---|
| `prisma/04-local-vs-prod.{en,ko}.png` | local baseline (no limits, no latency) vs production profile |
| `prisma/06-breakpoint.gif` | breaking-point search: double, then bisect → "holds up to N concurrent requests" (recorded before warm-up was added; the search itself is unchanged) |
| `prisma/07-hook-regression.gif` | opt-in hook: after an edit to `schema.prisma`, the quick check (22 s) flags queries/request 3.0 → 47.0 and exits 2 |

## Tools

- `_tools/record.sh` — records terminal GIFs with [vhs](https://github.com/charmbracelet/vhs)
- `_tools/shot_report.py` — renders a report (or selected sections) to PNG with headless Chrome (`markdown`, `Pillow`)
- `_tools/stack_flow.sh` — the full recorded flow per demo stack

```bash
resources/_tools/stack_flow.sh fastapi "FastAPI + SQLAlchemy" "<hash command>" <fixed-copy-dir>
SPEED=3 TITLE="..." resources/_tools/record.sh out.gif examples/demo-shop-prisma "catchme load"
python resources/_tools/shot_report.py report.md out.png --sections "Summary,Results"
```
