#!/bin/bash

# Format timetable.jsonl: remove spaces and sort

TIMETABLE_FILE="data/timetable.jsonl"

# Check if file exists
if [ ! -f "$TIMETABLE_FILE" ]; then
    echo "Error: $TIMETABLE_FILE not found"
    exit 1
fi

# Create temporary file
TEMP_FILE=$(mktemp)

# Remove all spaces and sort
cat "$TIMETABLE_FILE" | tr -d ' ' | sort > "$TEMP_FILE"

# Replace original file
mv "$TEMP_FILE" "$TIMETABLE_FILE"

echo "✓ Formatted $TIMETABLE_FILE"
echo "  - Removed all spaces"
echo "  - Sorted lines"
