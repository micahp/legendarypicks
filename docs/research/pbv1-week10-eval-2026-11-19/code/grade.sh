#!/bin/sh
# Merge each arm's box scores across the 14 games and grade them through the Oracle (read-only).
set -e
DATA=$1; OUT=$2; DB=$3; ORACLE=$4
for arm in A-control B-field C-field-pbv1; do
  mkdir -p "$OUT/batch/$arm"
  for f in "$DATA"/2026_10_*/runs/$arm/*.boxscores.jsonl; do ln -sf "$f" "$OUT/batch/$arm/$(basename "$f")"; done
done
python3 "$ORACLE" --db "$DB" --season 2026 --grade-week 10 \
  --batch A-control="$OUT/batch/A-control" --batch B-field="$OUT/batch/B-field" \
  --batch C-field-pbv1="$OUT/batch/C-field-pbv1" > "$OUT/oracle-grade.json"
echo graded
