#!/usr/bin/env bash
set -euo pipefail

JOBS="${JOBS:-4}"
echo "Rendering reports with JOBS=$JOBS"

tasks_file="$(mktemp)"

for f in corpus/sites/*.json; do
  echo "Site: $(basename "$f")"
  count=$(/opt/miniconda3/envs/pt1/bin/python - "$f" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
print(len(data.get("pages", [])))
PY
)
  if [ "$count" -eq 0 ]; then
    echo "  pages=0 (skip)"
    continue
  fi
  echo "  pages=$count"
  for i in $(seq 0 $((count - 1))); do
    printf '%s\t%s\n' "$f" "$i" >> "$tasks_file"
  done
done

cat "$tasks_file" | xargs -P "$JOBS" -n 2 bash -lc 'python scripts/render_extraction.py --site "$0" --index "$1"'
rm -f "$tasks_file"

echo "Done."
