# -*- coding: utf-8 -*-
"""Hand-authored Q&A overrides stored in local_qna.json.

A source for content that has no upstream home: a service notice, a correction,
a question the portal API does not carry, or an answer a domain expert wants
phrased a particular way. The entries live in `local_qna.json` next to this
file and are folded into the same build as every other source, so they get the
same canonicalisation, dedup and curation protection.

`add_qna.py` is the supported way to edit that file. This module only reads.

Entry shape (only `q` and `a` are required):

    {
      "q": "question as a user would type it",
      "a": "the answer, verbatim",
      "more": "optional extra answer for the same question",
      "category": "optional service category, e.g. khotian / namjari",
      "keyword": "optional short label for the entry",
      "tpl": false,          # true marks a statutory template answer
      "note": "why this entry exists / who approved it (never shown)"
    }

`category` is served verbatim by public_api, so a wrong value is visible in the
public API. Omit it and public_api falls back to its keyword classifier.
"""
import json
import os

from qa_dedup import canonical, clean_text, norm

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "local_qna.json")

REQUIRED = ("q", "a")


def load_entries(path=STORE):
    """Read the store. A missing file is an empty store, not an error."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = raw.get("entries", [])
    if not isinstance(raw, list):
        raise ValueError("local_qna.json must hold a list of entries")
    return raw


def validate(entries):
    """Return (clean_entries, problems) for raw store contents.

    Rejects entries that cannot become a usable row, and reports exact-question
    collisions inside the store itself.
    """
    out, problems = [], []
    seen = {}
    for i, e in enumerate(entries, start=1):
        if not isinstance(e, dict):
            problems.append(f"entry {i}: not an object")
            continue
        missing = [k for k in REQUIRED if not str(e.get(k) or "").strip()]
        if missing:
            problems.append(f"entry {i}: missing {' and '.join(missing)}")
            continue
        q = clean_text(e["q"])
        a = clean_text(e["a"])
        if len(norm(q)) < 2:
            problems.append(f"entry {i}: question is too short to match on")
            continue
        if len(a) < 10:
            problems.append(f"entry {i}: answer is too short ({len(a)} chars)")
            continue
        key = norm(q)
        if key in seen:
            problems.append(f"entry {i}: duplicate question, same as entry {seen[key]}")
            continue
        seen[key] = i
        ent = {"q": q, "a": a}
        if e.get("more"):
            ent["more"] = clean_text(e["more"])
        if e.get("category"):
            ent["category"] = str(e["category"]).strip().lower()
        if e.get("keyword"):
            ent["keyword"] = clean_text(e["keyword"])
        if e.get("tpl"):
            ent["tpl"] = True
        out.append(ent)
    return out, problems


def extract_local_entries(path=STORE):
    """Entries in build_db's {q, a, more?, tpl?, category?, keyword?} shape."""
    raw = load_entries(path)
    if not raw:
        return []
    entries, problems = validate(raw)
    for p in problems:
        print(f"[local_qna] skipped {p}")
    if not entries:
        return []
    print(f"[local_qna] {len(entries)} hand-authored Q&A")
    return entries


def save_entries(entries, path=STORE):
    """Write the store atomically so an interrupted run cannot truncate it."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def find_duplicates(q, dataset_rows):
    """Existing dataset rows whose normalized question matches `q`."""
    from qa_dedup import norm as _norm

    key = _norm(canonical(q))
    return [r for r in dataset_rows if _norm(r.get("q", "")) == key]
