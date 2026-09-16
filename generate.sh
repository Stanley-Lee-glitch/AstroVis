#!/usr/bin/env bash

OUT="astrovis.txt"
> "$OUT"

# 尋找目前目錄及所有子目錄下的 .py 和 .md 檔案
find . -type f \( -name "*.py" -o -name "*.md" \) | sort | while read -r f; do
    # 移除路徑開頭的 "./" 方便閱讀
    clean_path="${f#./}"
    
    echo "===== FILE: $clean_path =====" >> "$OUT"
    cat "$f" >> "$OUT"
    echo -e "\n\n" >> "$OUT"
done

echo "Dump written to $OUT ($(wc -l < "$OUT") lines)"
