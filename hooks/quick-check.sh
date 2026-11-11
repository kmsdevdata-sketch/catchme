#!/usr/bin/env bash
# catchme PostToolUse hook — quick queries-per-request regression check.
# Does nothing unless the project opted in with `catchme hooks on`.
# Exit 2 + stderr = feedback shown to the agent. Any other failure is swallowed (never block edits).

input="$(cat)"
root="${CLAUDE_PROJECT_DIR:-$PWD}"
flag="$root/.prod-parity/hooks.enabled"
[ -f "$flag" ] || exit 0

file="$(printf '%s' "$input" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
[ -n "$file" ] || exit 0

matched=0
# Default query-related patterns + extra glob patterns (one per line) in hooks.enabled
patterns="*Repository.java *Repository.kt *Mapper.xml *Dao.java *schema.prisma *repository*.ts *repository*.js *Repository.ts *models.py *managers.py *querysets.py *queries.py"
extra="$(grep -v '^[[:space:]]*#' "$flag" 2>/dev/null | tr '\n' ' ')"
set -f
for p in $patterns $extra; do
  # shellcheck disable=SC2254
  case "$file" in
    $p) matched=1; break ;;
  esac
done
set +f
[ "$matched" -eq 1 ] || exit 0

cm="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}/skills/catchme/scripts/catchme"
out="$(CATCHME_PROJECT="$root" "$cm" quick 2>&1)"
code=$?
if [ "$code" -eq 2 ]; then
  printf 'catchme quick check after editing %s:\n%s\n' "$file" "$out" >&2
  exit 2
fi
exit 0
