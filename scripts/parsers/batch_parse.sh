#!/bin/bash
# Batch driver for parse_lines.py — processes images in small batches to avoid
# the macOS Vision framework crashing from accumulated state.
# Usage: bash /tmp/batch_parse.sh <line> [batch_size]
LINE="$1"
BATCH="${2:-5}"
OUT="data/lines/${LINE}.jsonl"
TMPDIR="/tmp/batch_parse_${LINE}"
mkdir -p "$TMPDIR"
rm -f "$TMPDIR"/*.tmp
rm -f "$OUT"

# Count images
IMG_COUNT=$(ls timetables/${LINE}-*.jpg timetables/${LINE}-*.png 2>/dev/null | wc -l | tr -d ' ')
echo "Line $LINE: $IMG_COUNT images, batch size $BATCH"
START=0
BATCH_NUM=0
while [ $START -lt $IMG_COUNT ]; do
    BATCH_NUM=$((BATCH_NUM + 1))
    TMP_OUT="$TMPDIR/batch_${BATCH_NUM}.tmp"
    .venv/bin/python scripts/parsers/parse_lines.py -l "$LINE" -j 1 --start $START --count $BATCH -o "$TMP_OUT" 2>&1 | tail -1
    START=$((START + BATCH))
done

# Concatenate all batch files
cat "$TMPDIR"/*.tmp > "$OUT" 2>/dev/null
TOTAL=$(wc -l < "$OUT" 2>/dev/null)
echo "Done. Total records: $TOTAL -> $OUT"
