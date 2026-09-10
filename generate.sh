#!/usr/bin/env bash

OUT="astrovis.txt"
> "$OUT"

for dir in Backend Blender_Import Blender_Effect; do
    find "$dir" -type f \( -name "*.py" -o -name "*.md" \) | sort | while read -r f; do
        echo "===== FILE: $f =====" >> "$OUT"
        cat "$f" >> "$OUT"
        echo -e "\n" >> "$OUT"
    done
done

echo "Dump written to $OUT ($(wc -l < "$OUT") lines)"