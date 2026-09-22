#!/usr/bin/env bash
# After Claude edits a file, format it so layout never reaches review.
#   Python: ruff format, then the safe ruff fixes. Any lint error left goes back to Claude (exit 2
#           shows it stderr), so it's fixed now rather than in CI.
#   Web:    Prettier only. Type-aware ESLint takes seconds per file; scripts/check runs it.
#
# Unused imports and variables are neither removed nor reported here. Claude often adds an import in
# one edit and uses it in the next. scripts/check still catches them.
#
# A convenience, not a gate: without jq, uv or pnpm it does nothing. scripts/check is the gate.
set -uo pipefail
command -v jq >/dev/null || exit 0
file=$(jq -r '.tool_input.file_path // empty')
[[ -n "$file" && -f "$file" ]] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

case "$file" in
  */src/*.py | */tests/*.py)
    uv run --quiet ruff format --quiet "$file"
    if ! out=$(uv run --quiet ruff check --fix --quiet --extend-ignore F401,F841 "$file" 2>&1); then
      printf 'ruff still reports these in %s:\n%s\n' "$file" "$out" >&2
      exit 2
    fi
    ;;
  */web/src/*.ts | */web/src/*.tsx | */web/src/*.css)
    pnpm --dir web exec prettier --write --log-level warn "$file" >/dev/null
    ;;
esac
exit 0
