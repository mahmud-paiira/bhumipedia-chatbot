"""Q&A extraction from the live public API (bhumipedia.land.gov.bd).

The SQL dump in this repo mirrors the portal's iLKMS corpus: statutes,
schedules and definitions. What it does NOT contain is the portal's curated
citizen-service knowledge, which lives behind the Q&A endpoints:

    /api/v1/qna/type1/   1,065 rows  - curated service questions
    /api/v1/qna/type2/  24,995 rows  - the full Q&A table

Measured against data.js, 1,063 of the 1,065 type1 questions and 24,959 of
the 24,995 type2 questions were absent, so this is additive content rather
than a re-read of the dump.

Two things to be careful about:

  * type1 and type2 are separate tables with COLLIDING id spaces (type1 ids
    run 24776..25878, type2 ids 2843..28080, and 1,056 ids appear in both
    carrying different questions). `id` is therefore not a global key and is
    never used for merging - the union is keyed on normalised question text.
    Answers agree wherever a question appears in both.
  * both endpoints return a bare JSON array unless `page` is passed, so paging
    is explicit and bounded by page_size=1000.
  * the table mixes real service questions with individual citizen case
    narratives, which are not answerable knowledge - see is_case_narrative().
  * questions arrive with deprecated Bengali codepoints (U+09DF/U+09DD); they
    are canonicalised on the way in - see qa_dedup.canonical().

Categories and keywords come from the service, so they are real taxonomy
rather than the keyword heuristics in public_api.py, which agree with the
service on only 55.8% of the questions the service actually labels.

Responses are cached under `api_cache/` so a build never depends on the host
being online; re-fetch with `python api_source.py --refresh`.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

from qa_dedup import canonical

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "api_cache")
BASE = "https://bhumipedia.land.gov.bd"
ENDPOINTS = {
    "type1": "/api/v1/qna/type1/",
    "type2": "/api/v1/qna/type2/",
}
PAGE_SIZE = 1000
MAX_ANS = 4000
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def strip_html(s):
    s = TAG_RE.sub(" ", str(s or ""))
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return WS_RE.sub(" ", s).strip()


def _fetch(url, tries=3, timeout=240):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bhumipedia-chatbot-build/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # network flake; retry
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError("GET %s failed: %s" % (url, last))


def fetch_endpoint(kind, refresh=False):
    """Return the full row list for a Q&A endpoint, using the disk cache."""
    path = os.path.join(CACHE_DIR, kind + ".json")
    if not refresh and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    os.makedirs(CACHE_DIR, exist_ok=True)
    url = BASE + ENDPOINTS[kind]
    first = _fetch(url + "?page=1&page_size=%d" % PAGE_SIZE)
    if not isinstance(first, dict):  # bare array -> no paging, no envelope
        rows = first
    else:
        rows = list(first.get("results") or [])
        total = first.get("count")
        while len(rows) < (total or 0):
            nxt = first.get("next")
            if not nxt:
                break
            first = _fetch(nxt)
            batch = first.get("results") or []
            if not batch:
                break
            rows.extend(batch)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    return rows


# Citizen grievance narratives share the Q&A table with real service questions.
# A question like "আমাদের জমির সকল কাগজ সঠিক। নিয়মিত খাজনা দিয়ে আসতেছি। ভূমি
# দস্যুরা আমাদের ভূমি দখল করার কারণ..." is an individual case history, not
# answerable knowledge: it matches unrelated queries by token overlap and makes
# the bot answer confidently with the wrong thing. Case narratives are dropped.
FIRST_PERSON = ("আমার ", "আমাদের ", "আমি ", "আমারা ")


def is_case_narrative(q):
    q = str(q or "").strip()
    if len(q) > 110:
        return True
    if q.startswith(FIRST_PERSON):
        return True
    return q.count("।") >= 3


def extract_api_entries(refresh=False):
    """Curated Q&A items in build_db's {q, a, more?, tpl?} shape.

    type2 is 94% redundant upstream - 24,995 rows but only ~1,370 distinct
    questions (one appears 108 times) - so rows are grouped by normalised
    question and collapsed. A handful of questions legitimately carry more
    than one distinct answer; those extras are folded into `more` so nothing
    is discarded. type1 is read first so its curated category/keyword wins.
    """
    best = {}
    order = []
    dropped = 0
    for kind in ("type1", "type2"):
        try:
            rows = fetch_endpoint(kind, refresh=refresh)
        except Exception as e:  # the API is optional; never fail a build on it
            print("[api_source] %s unavailable: %s" % (kind, e))
            continue
        for r in rows:
            q = canonical(WS_RE.sub(" ", str(r.get("question") or "")).strip())
            a = canonical(WS_RE.sub(" ", strip_html(r.get("answer"))).strip())
            if not q or len(a) < 5:
                continue
            if is_case_narrative(q):
                dropped += 1
                continue
            key = re.sub(r"\s+", " ", q.lower()).strip()
            cur = best.get(key)
            if cur is None:
                best[key] = {"q": q, "answers": [a],
                             "category": (r.get("category") or "").strip() or None,
                             "keyword": (r.get("keyword") or "").strip() or None}
                order.append(key)
            elif a not in cur["answers"]:
                cur["answers"].append(a)
        print("[api_source] %s: %d rows scanned, %d distinct kept so far"
              % (kind, len(rows), len(best)))
    if dropped:
        print("[api_source] dropped %d citizen case narratives" % dropped)

    out = []
    for key in order:
        it = best[key]
        answers = it["answers"]
        # longest answer is the most complete; the rest become `more`
        answers = sorted(answers, key=len, reverse=True)
        a = answers[0]
        if len(a) > MAX_ANS:
            a = a[:MAX_ANS].rstrip() + "…"
        ent = {"q": it["q"], "a": a, "tpl": False,
               "category": it["category"], "keyword": it["keyword"]}
        extra = [x for x in answers[1:] if x not in a and len(x) >= 5]
        if extra:
            ent["more"] = ("\n\n".join(extra))[:MAX_ANS]
        out.append(ent)
    return out


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    items = extract_api_entries(refresh="--refresh" in sys.argv)
    print("extract_api_entries(): %d entries" % len(items))
    for it in items[:5]:
        print("  [%s] %s" % (it.get("category"), it["q"][:76]))
        print("        %s" % it["a"][:76].replace("\n", " "))
