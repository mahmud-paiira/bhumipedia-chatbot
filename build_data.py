import json
import os

from build_db import SQL_PATH, extract_db
from qa_dedup import clean_rows, load_curated

HERE = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(HERE, "data.js")

def rows_from_sources():
    """Every source -> cleaned, deduped rows. Shared with add_qna.py --check."""
    return clean_rows(extract_db(), load_curated())


def write_dataset(rows, dst=DST):
    """Write data.js atomically so a reader never sees a half-written file."""
    tmp = dst + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("const DATASET = ")
        json.dump(rows, f, ensure_ascii=False)
        f.write(";\n")
    os.replace(tmp, dst)


def main():
    items = extract_db()
    rows = clean_rows(items, load_curated())
    write_dataset(rows)
    print(f"OK: {len(rows)} entries -> data.js (src-candidates={len(items)}); "
          f"all data from {os.path.basename(SQL_PATH)}")


if __name__ == "__main__":
    main()
