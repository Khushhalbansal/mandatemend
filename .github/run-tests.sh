#!/usr/bin/env bash
# CI helper: run a pytest slice; on failure, emit the tail as a GitHub ::error:: annotation
# (log download needs auth we don't have, but annotations are readable via the public API).
set -u
label="$1"; shift
paths="$1"; shift
log="/tmp/pytest-${label}.log"

# `python -m pytest` (not bare `pytest`) so the repo root is on sys.path even before the
# pythonpath=["."] ini option kicks in.
# shellcheck disable=SC2086
python -m pytest -q -rA -p no:cacheprovider ${paths} "$@" >"$log" 2>&1
rc=$?
cat "$log"
if [ "$rc" -ne 0 ]; then
  python - "$log" "$label" <<'PY'
import sys, urllib.parse
log, label = sys.argv[1], sys.argv[2]
txt = open(log, encoding="utf-8", errors="replace").read()[-4000:]
print("::error title=" + label + "-tests::" + urllib.parse.quote(txt))
PY
fi
exit $rc
