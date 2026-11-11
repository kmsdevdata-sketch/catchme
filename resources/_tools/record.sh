#!/usr/bin/env bash
# Record a terminal GIF of catchme commands with vhs (https://github.com/charmbracelet/vhs).
#
#   record.sh OUT.gif PROJECT_DIR "cmd 1" "cmd 2" ...
#
# Env: SPEED (playback speed, default 2), WIDTH/HEIGHT (px), FONT_SIZE, TITLE (echoed first).
# `catchme` is on PATH inside the recording. Each command waits for the prompt before the next.
set -euo pipefail

out="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
dir="$(cd "$2" && pwd)"
shift 2
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
bin="$(mktemp -d)"
ln -s "$repo/skills/catchme/scripts/catchme" "$bin/catchme"
tape="$(mktemp -t catchme-tape).tape"
log="${RECORD_LOG:-$out.log}"
: >"$log"

{
  echo "Output \"$out\""
  echo 'Set Shell "bash"'
  echo 'Set FontFamily "JetBrainsMonoNL Nerd Font"'
  echo "Set FontSize ${FONT_SIZE:-15}"
  echo "Set Width ${WIDTH:-1400}"
  echo "Set Height ${HEIGHT:-820}"
  echo 'Set Padding 24'
  echo 'Set Theme "GitHub Dark"'
  echo 'Set TypingSpeed 35ms'
  echo "Set PlaybackSpeed ${SPEED:-2}"
  echo 'Set WindowBar Colorful'
  echo 'Hide'
  echo "Type \"export PATH='$bin':\$PATH PS1='> ' BASH_SILENCE_DEPRECATION_WARNING=1 PROMPT_COMMAND='echo \$(date +%T) done >> $log' && cd '$dir' && clear\""
  echo 'Enter'
  echo 'Sleep 500ms'
  echo 'Show'
  if [ -n "${TITLE:-}" ]; then
    printf 'Type "# %s"\nSleep 800ms\nEnter\n' "$TITLE"
  fi
  for c in "$@"; do
    # vhs has no escapes inside strings: pick a delimiter the command does not contain
    case "$c" in
      *'`'*) case "$c" in *'"'*) q="'" ;; *) q='"' ;; esac ;;
      *) q='`' ;;
    esac
    case "$c" in *"$q"*) echo "record.sh: cannot quote command for vhs: $c" >&2; exit 1 ;; esac
    printf 'Type %s%s%s\nSleep 400ms\nEnter\nWait+Line@900s />\\s*$/\nSleep 2500ms\n' "$q" "$c" "$q"
  done
  echo 'Sleep 3s'
} >"$tape"

vhs "$tape" >/dev/null &
vpid=$!
limit="${MAX_SECONDS:-1500}"
t=0
while kill -0 "$vpid" 2>/dev/null; do
  sleep 2; t=$((t + 2))
  if [ "$t" -ge "$limit" ]; then
    kill "$vpid" 2>/dev/null
    echo "record.sh: vhs exceeded ${limit}s — killed. Prompt log ($log):" >&2
    cat "$log" >&2
    rm -rf "$bin" "$tape"
    exit 1
  fi
done
wait "$vpid"
rm -rf "$bin" "$tape" "$log"
echo "$out ($(du -h "$out" | cut -f1))"
