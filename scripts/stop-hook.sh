#!/usr/bin/env bash
# Claude Code hook: an agent session can't finish while `make check` fails.
# Wired up in .claude/settings.json. Tested by tests/test_stop_hook.py.
#
#   stop-hook.sh                 Stop hook. Runs the check; exit 2 + output on stderr blocks.
#   stop-hook.sh session-start   SessionStart hook. Records the starting HEAD as the
#                                baseline, so a chat-only session is never blocked.
#
# Skips the check when the working tree is clean and HEAD equals the stamp (the
# session-start baseline or the last commit that passed). Loop guard: when Claude is
# already continuing because of this hook (stop_hook_active), it blocks at most
# OSP_STOP_HOOK_MAX_BLOCKS times in a row (default 3, the "3 strikes" guardrail),
# then lets the session end with a message to mark the task blocked.
#
# Env overrides (for tests): OSP_STOP_HOOK_CMD (default "make check"),
# OSP_STOP_HOOK_MAX_BLOCKS.
set -uo pipefail

mode="${1:-stop}"
input="$(cat 2>/dev/null || true)"

# The first Python that really runs. On Windows `python3` may be the Microsoft Store's
# "install Python" stub, which prints an advert and fails: skip it.
python=""
for candidate in python3 python py; do
	if "$candidate" -c 'import sys' >/dev/null 2>&1; then
		python="$candidate"
		break
	fi
done

json_field() { # json_field <key>: print a top-level field of the hook's stdin JSON
	if [ -n "$python" ]; then
		# end="" (not print's newline): Python on Windows would write CRLF, and $(...)
		# strips only the LF, leaving a CR on the path.
		printf '%s' "$input" | "$python" -c '
import json, sys
try:
    v = json.load(sys.stdin).get(sys.argv[1], "")
except Exception:
    v = ""
print(str(v).lower() if isinstance(v, bool) else v, end="")' "$1"
	else
		printf '%s' "$input" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\{0,1\}\([^\",}]*\).*/\1/p" | head -n1
	fi
}

cwd="$(json_field cwd)"
start="${cwd:-${CLAUDE_PROJECT_DIR:-$PWD}}"
root="$(git -C "$start" rev-parse --show-toplevel 2>/dev/null)" || exit 0 # not a repo: nothing to guard
cd "$root" || exit 0

state_dir="$root/.claude"
stamp="$state_dir/.stop-hook-stamp"
blocks_file="$state_dir/.stop-hook-blocks"
mkdir -p "$state_dir"
head="$(git rev-parse -q --verify HEAD 2>/dev/null || echo none)"
clean() { [ -z "$(git status --porcelain)" ]; }

if [ "$mode" = "session-start" ]; then
	if clean; then printf '%s\n' "$head" >"$stamp"; fi
	rm -f "$blocks_file"
	exit 0
fi

if clean && [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$head" ]; then
	rm -f "$blocks_file"
	exit 0 # nothing changed since the last green check / session start
fi

max_blocks="${OSP_STOP_HOOK_MAX_BLOCKS:-3}"
blocks=0
if [ "$(json_field stop_hook_active)" = "true" ]; then
	blocks="$(cat "$blocks_file" 2>/dev/null || echo 0)"
	if [ "$blocks" -ge "$max_blocks" ]; then
		rm -f "$blocks_file"
		echo "stop-hook: make check still failing after $blocks attempts; letting the session end." >&2
		echo "stop-hook: mark the task 'blocked' in planning/tasks.md with notes (AGENTS.md §6)." >&2
		exit 0
	fi
fi

check_cmd="${OSP_STOP_HOOK_CMD:-make check}"
output="$(bash -c "$check_cmd" 2>&1)"
status=$?

if [ "$status" -eq 0 ]; then
	printf '%s\n' "$head" >"$stamp"
	rm -f "$blocks_file"
	exit 0
fi

echo $((blocks + 1)) >"$blocks_file"
{
	echo "\`$check_cmd\` failed (exit $status). Fix it before finishing (attempt $((blocks + 1))/$max_blocks)."
	echo "--- last 80 lines ---"
	printf '%s\n' "$output" | tail -n 80
} >&2
exit 2
