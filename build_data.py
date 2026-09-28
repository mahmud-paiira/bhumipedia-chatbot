import json
import os
import re

from build_db import extract_db

HERE = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(HERE, "data.js")


def norm(s):
    s = str(s).lower()
    s = re.sub(r"[^\w\u0980-\u09FF]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_text(s):
    return re.sub(r"[ \t\u00a0]+", " ", str(s)).strip()


rows = []
seen = set()
items = extract_db()
added = 0
for it in items:
    q = clean_text(it["q"])
    a = clean_text(it["a"])
    k = norm(q)
    if len(k) < 2 or len(a) < 10 or k in seen:
        continue
    seen.add(k)
    ent = {"q": q, "a": a}
    if it.get("more"):
        ent["more"] = clean_text(it["more"])
    if it.get("tpl"):
        ent["t"] = 1
    rows.append(ent)
    added += 1

with open(DST, "w", encoding="utf-8") as f:
    f.write("const DATASET = ")
    json.dump(rows, f, ensure_ascii=False)
    f.write(";\n")

print(f"OK: {len(rows)} entries -> data.js (ilks-db={added}, "
      f"src-candidates={len(items)}); all data from {os.path.basename(__import__('build_db').SQL_PATH)}")