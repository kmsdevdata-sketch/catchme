#!/usr/bin/env bash
# Full catchme flow for one demo stack, recording resources along the way.
#
#   stack_flow.sh <key> <label> <hash-command> <fix-dir>
#     key     demo folder suffix (examples/demo-shop-<key>) and resources/<key>/
#     label   human name for titles/badges, ASCII only (vhs)
#     hash    command printing the test password hash inside the app container (via `catchme exec app ...`)
#     fix-dir directory with the fixed version of the demo (for `catchme verify`)
#
# Writes resources/<key>/: 01-setup.gif, 02-load-report.gif, 03-report-summary.{en,ko}.png,
# 04-breakpoint.png (from report), 05-before-after.{en,ko}.png and the raw reports.
set -euo pipefail
key="$1" label="$2" hash_cmd="$3" fix="$4"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
demo="$repo/examples/demo-shop-$key"
res="$repo/resources/$key"
cm="$repo/skills/catchme/scripts/catchme"
py="${SHOT_PY:-python3}"
mkdir -p "$res"
step() { printf '\n=== [%s] %s (%s)\n' "$key" "$*" "$(date +%T)"; }

step "reset"
(cd "$demo" && "$cm" teardown >/dev/null 2>&1 || true)
(cd "$demo/.prod-parity" && rm -rf reports runs state scenarios db-init project.json profile.yaml docker-compose*.yml env.*.sh toxiproxy.json query-baseline.json .gitignore ./*.example.yaml)

step "record setup"
SPEED=3 MAX_SECONDS=1500 TITLE="$label: production profile in local Docker" "$here/record.sh" "$res/01-setup.gif" "$demo" \
  "catchme init" \
  "catchme profile --app-preset ecs-fargate:0.5vcpu-1gb --db-preset rds:db.t3.micro --latency-ms 1" \
  "catchme gen" \
  "catchme up" \
  "catchme status | tail -4" \
  "H=\$($hash_cmd) && sed -i '' \"s|__PASSWORD_HASH__|\$H|\" .prod-parity/seed.yaml && grep password_hash .prod-parity/seed.yaml" \
  "catchme seed 2>&1 | grep -v '^\$'"
grep -q "__PASSWORD_HASH__" "$demo/.prod-parity/seed.yaml" && { echo "password hash was not filled in"; exit 1; }

step "record load + report"
SPEED=2 MAX_SECONDS=900 TITLE="$label: auth, steady load, 100 simultaneous orders" "$here/record.sh" "$res/02-load-report.gif" "$demo" \
  "catchme load 2>&1 | grep catchme" \
  "catchme report 2>/dev/null" \
  "sed -n '1,16p' .prod-parity/reports/latest.md"

[ -f "$demo/.prod-parity/runs/prod/metrics.json" ] || { echo "load failed — see $res/02-load-report.gif"; exit 1; }

step "breakpoint"
(cd "$demo" && "$cm" breakpoint 2>&1 | grep 'breakpoint')

step "reports + screenshots"
(cd "$demo" && "$cm" report --lang en >/dev/null 2>&1 && cp .prod-parity/reports/latest.md "$res/report-prod.en.md" \
  && "$cm" report --lang ko >/dev/null 2>&1 && cp .prod-parity/reports/latest.md "$res/report-prod.ko.md")
"$py" "$here/shot_report.py" "$res/report-prod.en.md" "$res/03-report-summary.en.png" --sections "Summary,Results,Bottleneck" --badge "$label"
"$py" "$here/shot_report.py" "$res/report-prod.ko.md" "$res/03-report-summary.ko.png" --sections "요약,결과,병목" --badge "$label"

step "verify (fixed version)"
(cd "$demo" && "$cm" verify "$fix" 2>&1 | grep '\[catchme\]' | grep -v warning)
(cd "$demo" && cp .prod-parity/reports/latest.md "$res/report-after-fix.en.md" \
  && "$cm" report --label after --before prod --lang ko >/dev/null 2>&1 && cp .prod-parity/reports/latest.md "$res/report-after-fix.ko.md")
"$py" "$here/shot_report.py" "$res/report-after-fix.en.md" "$res/05-before-after.en.png" --sections "Before" --badge "$label: catchme verify"
"$py" "$here/shot_report.py" "$res/report-after-fix.ko.md" "$res/05-before-after.ko.png" --sections "수정 전후" --badge "$label: catchme verify"

step "teardown"
(cd "$demo" && "$cm" teardown 2>&1 | tail -1)
step "done"
ls "$res"
