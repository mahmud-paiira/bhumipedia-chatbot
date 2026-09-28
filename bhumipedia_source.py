"""Q&A extraction from the public Bhumipedia portal (bhumipedia.land.gov.bd).

The portal's /acts page is a React SPA; its data comes from an open Django REST
API. This module reads that API directly:

    /api/acts/  /api/sections/  /api/subsections/
    /api/schedules/  /api/subschedules/  /api/ebooks/  /api/blogs/

The portal mirrors the same iLKMS corpus as the SQL dump, organised as the
Bangladesh land-law hierarchy:

    শিরোনাম   (heading)     - the title of a section / schedule
    বিষয়বস্তু  (content)    - the clause body
    ধারা      (section)     - a numbered section of an act
    উপধারা    (subsection)  - a lettered/numbered clause inside a section
    দফা       (clause item) - the parenthesised items inside a body

The gap this fills: on the portal a large share of sections carry a real
শিরোনাম but an *empty* বিষয়বস্তু, because the wording lives in their উপধারা
rows. build_db.extract_db() requires a non-empty section body, so it emits
nothing for those ধারা. Here the body is composed from the children, which
makes every ধারা answerable, and the তফসিল/দফা levels are emitted too.

Responses are cached under `bhumipedia_cache/` so a build never depends on the
portal being online; re-fetch with `python bhumipedia_source.py --refresh`.
"""

import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "bhumipedia_cache")
BASE = "https://bhumipedia.land.gov.bd/api"
COLLECTIONS = [
    "acts",
    "sections",
    "subsections",
    "schedules",
    "subschedules",
    "ebooks",
    "blogs",
]

BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
BENGALI_RE = re.compile(r"[\u0980-\u09FF]")
ITEM_NUM_RE = re.compile(r"^\(?[\u09e7\u09e6-\u09ef0-9]{1,3}\)?$")
ITEM_ALPHA_RE = re.compile(r"^\(?[\u0995-\u09b9]{1,3}\)?$")
SCHED_WORD = {
    "ক": "প্রথম", "খ": "দ্বিতীয়", "গ": "তৃতীয়", "ঘ": "চতুর্থ", "ঙ": "পঞ্চম",
    "চ": "ষষ্ঠ", "ছ": "সপ্তম", "জ": "অষ্টম", "ঝ": "নবম", "ঞ": "দশম",
    "ঠ": "একাদশ", "ড": "দ্বাদশ", "ঢ": "ত্রয়োদশ",
}
MIN_TITLE = 10
MIN_BODY = 60
MIN_HEADING = 6
MAX_SECTIONS_PER_DOC = 120


def _txt(raw):
    """Collapse an HTML field into a single clean line."""
    s = re.sub(r"<br\s*/?>", " ", str(raw or ""), flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&quot;", '"').replace("&#39;", "'")
          .replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"\s+", " ", s).strip()


NUM_STRIP = "\"'“”‘’`।.[]() \t\u00a0"
NUM_BN = re.compile(r"^[০-৯]{1,3}[ক-হ]?$")
NUM_EN = re.compile(r"^[0-9]{1,3}[a-zA-Z]?$")


def _letters(s):
    """True when s is 1-4 standalone letters (no Bengali matras or viramas)."""
    if not s or len(s) > 4:
        return False
    return all(unicodedata.category(c) in ("Lo", "Ll", "Lu") for c in s)


def _num(raw):
    """Clean a ধারা/উপধারা/তফসিল number, or return "" if it is not one.

    The portal's ``number`` column is dirty: alongside clean values like
    ``(১)`` / ``(ক)`` / ``7`` it holds ``“(২``, ``[(৪ক)``, ``৯০[***]``,
    ``ব্যাখ্যা।-``, ``Test Upodhara 1`` and ``34546``. Those used to leak into
    questions as ``উপধারা “(২) এ কী বলা হয়েছে?``, so anything that is not a
    plausible clause number is now dropped and the caller falls back to the
    section heading.
    """
    s = _txt(raw)
    if not s:
        return ""
    had_paren = s.lstrip().startswith("(") or s.rstrip().endswith(")")
    core = s.strip(NUM_STRIP).strip("()").strip(NUM_STRIP)
    if not core or "*" in core or "°" in core or "[" in core:
        return ""
    if not (NUM_BN.match(core) or NUM_EN.match(core)
            or _letters(core) and (BENGALI_RE.search(core) or had_paren)):
        return ""
    core = core.translate(BN_DIGITS)
    if not re.sub(r"[০0]", "", core):
        return ""
    return f"({core})" if had_paren else core


def _head(raw):
    """Normalise a শিরোনাম: strip trailing danda / dash / dot noise."""
    h = _txt(raw)
    h = re.sub(r"[\s।\.।–—\-:]+$", "", h)
    return h.strip()


LOREM_RE = re.compile(
    r"(?i)lorem|ipsum|dolor sit|consectetur|adipis|aliqua|excepteur|"
    r"sunt in culpa|nulla pari|deserunt mollit|in voluptate|"
    r"magna aliqua|exercitation ullamco|reprehenderit|"
    r"laboris nisi|ut enim|minim veniam|tempor incididunt")
JUNK_TITLE_RE = re.compile(
    r"(?i)^(test|proma|demo|dummy|saba|fdfd|asdf|abc|xyz|qwer|lorem|ipsum)\d*"
    r"|\btest\b|\bdemo\b|\bdummy\b|\bproma\b|\blorem\b|\bipsum\b")


def _junk(s):
    """Reject empty, corrupted, keyboard-mash and lorem-ipsum text."""
    t = s.strip()
    if len(t) < 4 or "????" in t:
        return True
    if LOREM_RE.search(t):
        return True
    if BENGALI_RE.search(t):
        return False
    words = re.findall(r"[A-Za-z]{2,}", t)
    if not words:
        return True
    for w in words:
        if not any(v in w.lower() for v in "aeiou"):
            return True  # hjk, sdfgh, ASDRTFYUIOP, DFGBDFBDFG
    return False


def _good_title(t):
    """A usable document title (reject test rows, stubs and lorem filler)."""
    t = _txt(t)
    if len(t) < MIN_TITLE or _junk(t):
        return False
    if JUNK_TITLE_RE.search(t):
        return False
    return True


def _summarize(body, head):
    """Headline + body, without repeating the lead sentence twice.

    Same shape as build_db.section_summary(), but the lead sentence is removed
    from the body so the composed ধারা answer does not open with it twice.
    """
    first = re.split(r"[।\n]", body)[0].strip(" ;,।") if body else ""
    rest = body
    if first and body.startswith(first):
        rest = body[len(first):].lstrip(" ;,।\n")
    summ = re.sub(r"\s+", " ", rest).strip()
    if len(summ) > 900:
        summ = summ[:900].rstrip() + "…"
    lead = first if first and len(first) >= 15 else ""
    if lead:
        return f"{head}: {lead}।\n\n{summ}" if summ else f"{head}: {lead}।"
    return summ


def _doc_universe(cols):
    """Map document id -> title for every titled act/ebook the portal exposes.

    The portal's /api/acts/ only lists the headline acts, but sections also
    hang off ordinances, rules, manuals and circulars that appear in
    /api/ebooks/. Both are merged so a ধারা can always be named.
    """
    uni = {}
    for coll in ("acts", "ebooks"):
        for rec in cols.get(coll, []):
            title = _txt(rec.get("title_of_act"))
            if not _good_title(title):
                continue
            if rec.get("is_draft"):
                continue
            if rec.get("approved") is False:
                continue
            uni.setdefault(rec["id"], title)
    return uni


def fetch(force=False, timeout=300):
    """Return {collection: [records]}, using the on-disk cache when present."""
    if force or not os.path.isdir(CACHE_DIR):
        import requests

        os.makedirs(CACHE_DIR, exist_ok=True)
        sess = requests.Session()
        for coll in COLLECTIONS:
            path = os.path.join(CACHE_DIR, coll + ".json")
            if os.path.exists(path) and not force:
                continue
            try:
                resp = sess.get(f"{BASE}/{coll}/", timeout=timeout,
                                headers={"Accept": "application/json"})
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    data = data.get("results", data)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            except Exception as e:  # keep whatever is already cached
                print(f"[bhumipedia] fetch {coll} failed: {e}")

    cols = {}
    for coll in COLLECTIONS:
        path = os.path.join(CACHE_DIR, coll + ".json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                try:
                    cols[coll] = json.load(f)
                except ValueError:
                    cols[coll] = []
        else:
            cols[coll] = []
    return cols


def extract_bhumipedia_entries(cols=None):
    """Return a list of {q, a, more, tpl} items derived from the Bhumipedia API."""
    import build_db as b

    if cols is None:
        cols = fetch()

    out = []
    taken = set()

    def add(q, a_raw, title=None, more_raw=None):
        a = b.strip_html(a_raw)
        if len(a) > b.MAX_ANS:
            a = a[:b.MAX_ANS].rstrip() + "…"
        if len(a) < 10 or "????" in q or "????" in a:
            return False
        key = re.sub(r"\s+", " ", q.lower()).strip()
        if key in taken and title:
            key = re.sub(r"\s+", " ", f"{key} ({title})").strip()
        if key in taken:
            return False
        taken.add(key)
        e = {"q": q, "a": a, "tpl": False}
        if more_raw is not None:
            m = b.strip_html(more_raw)
            if m and len(m) > len(a):
                e["more"] = (m[:b.MAX_ANS].rstrip() + "…" if len(m) > b.MAX_ANS else m)
        out.append(e)
        return True

    def add_many(qs, a_raw, title=None, more_raw=None):
        return sum(1 for q in qs if add(q, a_raw, title, more_raw))

    universe = _doc_universe(cols)
    if not universe:
        return out

    # index children by parent
    subs_by_sec = {}
    for rec in cols.get("subsections", []):
        subs_by_sec.setdefault(rec.get("section_id"), []).append(rec)
    sch_by_sec = {}
    for rec in cols.get("schedules", []):
        sch_by_sec.setdefault(rec.get("section_id"), []).append(rec)
    sch_by_sub = {}
    for rec in cols.get("schedules", []):
        sch_by_sub.setdefault(rec.get("sub_section_id"), []).append(rec)
    sub_by_id = {rec.get("id"): rec for rec in cols.get("subsections", [])}

    secs_by_doc = {}
    for rec in cols.get("sections", []):
        secs_by_doc.setdefault(rec.get("act_id"), []).append(rec)

    def order(recs, idkey="id"):
        return sorted(recs, key=lambda r: r.get(idkey) or 0)

    for doc_id, title in sorted(universe.items(), key=lambda kv: kv[1]):
        doc_secs = secs_by_doc.get(doc_id) or []
        if not doc_secs:
            continue

        # ---- act-level intro (শিরোনাম of the document itself) ----
        meta = next((r for r in cols.get("acts", []) if r.get("id") == doc_id), None) \
            or next((r for r in cols.get("ebooks", []) if r.get("id") == doc_id), None) or {}
        for field in ("objective", "proposal"):
            body = _txt(meta.get(field))
            if len(body) >= 40 and not _junk(body):
                add_many([f"{title} কি?", f"{title} সম্পর্কে বিস্তারিত",
                          f"{title} এর উদ্দেশ্য কি?"], body, title)
                break

        for sec in order(doc_secs)[:MAX_SECTIONS_PER_DOC]:
            sec_num = _num(sec.get("number"))
            heading = _head(sec.get("heading"))
            body = _txt(sec.get("content"))
            head_ok = len(heading) >= MIN_HEADING and not _junk(heading)
            body_ok = len(body) >= MIN_BODY and not _junk(body)

            # উপধারা rows of this ধারা, paired with their own বিষয়বস্তু
            kids = []
            for k in order(subs_by_sec.get(sec.get("id")) or []):
                kt = _txt(k.get("content"))
                if len(kt) >= 15 and not _junk(kt):
                    kids.append((k, kt))
            # তফসিল rows hanging off this ধারা (or its উপধারা)
            sch_rows = list(sch_by_sec.get(sec.get("id")) or [])
            for k in kids:
                sch_rows += sch_by_sub.get(k[0].get("id")) or []
            schs = []
            for srow in order(sch_rows):
                st = _txt(srow.get("content"))
                if len(st) >= 15 and not _junk(st):
                    schs.append((srow, st))

            # ---- শিরোনাম-only ধারা: compose the বিষয়বস্তু from উপধারা ----
            if head_ok and not body_ok and kids:
                composed = " ".join(t for _, t in kids)
                head = f"ধারা {sec_num} — {heading}" if sec_num else heading
                ans = _summarize(composed, head)
                label = f"{title} এর ধারা {sec_num}" if sec_num else f"{title} এর {heading}"
                qs = [f"{label} কি বলে?",
                      f"{label} ({heading}) কী বলে?",
                      f"{label} এর বিধান কি?",
                      f"{label} এর শিরোনাম কি?",
                      f"{title} অনুযায়ী ধারা {sec_num} কি আছে?" if sec_num else f"{title} অনুযায়ী {heading} কি আছে?",
                      f"{heading} কি?"]
                add_many(qs, ans, title, composed)
                # দফা items inside the composed বিষয়বস্তু
                for marker, itext in b.extract_clause_index(composed):
                    add_many([f"{label} এর দফা {marker} এ কী বলা হয়েছে?",
                              f"{title} অনুযায়ী ধারা {sec_num} এর দফা {marker} এ কি?",
                              f"{marker} দফায় কি বলা হয়েছে?"],
                             itext, title, composed)
                for fq, fa in b.fact_questions(composed, head, title):
                    add(fq, fa, title, composed)

            # ---- ধারা with a real বিষয়বস্তু ----
            elif head_ok and body_ok:
                head = f"ধারা {sec_num} — {heading}" if sec_num else heading
                ans = _summarize(body, head)
                label = f"{title} এর ধারা {sec_num}" if sec_num else f"{title} এর {heading}"
                qs = [f"{label} কি বলে?",
                      f"{label} ({heading}) কী বলে?",
                      f"{label} এর বিধান কি?",
                      f"{title} অনুযায়ী ধারা {sec_num} কি আছে?" if sec_num else "",
                      f"{heading} কি?"]
                add_many([q for q in qs if q], ans, title, body)
                for fq, fa in b.fact_questions(body, head, title):
                    add(fq, fa, title, body)

            # ---- উপধারা (and দফা-style parenthesised clauses) ----
            for kid, ktext in kids:
                knum = _num(kid.get("number"))
                if not knum:
                    continue
                khead = _head(kid.get("heading"))
                sub_head = khead or (f"{heading} {knum}" if head_ok else f"উপধারা {knum}")
                if sec_num:
                    lab = f"{title} এর ধারা {sec_num} উপধারা {knum}"
                else:
                    lab = f"{title} এর উপধারা {knum}"
                is_dafa = bool(ITEM_NUM_RE.match(knum) or ITEM_ALPHA_RE.match(knum))
                qs = [f"{lab} এ কী বলা হয়েছে?",
                      f"{lab} কি বলে?",
                      f"ধারা {sec_num} এর উপধারা {knum} কি বলে?" if sec_num else ""]
                if is_dafa:
                    qs.append(f"{title} এর ধারা {sec_num} এর দফা {knum} এ কী বলা হয়েছে?"
                              if sec_num else f"{title} এর দফা {knum} কি?")
                add_many([q for q in qs if q], ktext, title, ktext)
                for fq, fa in b.fact_questions(ktext, sub_head, title):
                    add(fq, fa, title, ktext)

            # ---- তফসিল ----
            for srow, stext in schs:
                mnum = _num(srow.get("number"))
                if not mnum:
                    continue
                word = SCHED_WORD.get(mnum.strip("()"))
                ord_label = f"{word} তফসিল" if word else f"তফসিল {mnum}"
                if sec_num:
                    lab = f"{title} এর ধারা {sec_num} এর {ord_label}"
                else:
                    lab = f"{title} এর {ord_label}"
                add_many([f"{lab} কি বলে?",
                          f"{lab} এ কী বলা হয়েছে?",
                          f"{title} এর {ord_label} কী?"],
                         stext, title, stext)
                for fq, fa in b.fact_questions(stext, ord_label, title):
                    add(fq, fa, title, stext)

    return out


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    refresh = "--refresh" in sys.argv
    cols = fetch(force=refresh)
    counts = {k: len(v) for k, v in cols.items()}
    print(f"[bhumipedia] collections: {counts}")
    items = extract_bhumipedia_entries(cols)
    print(f"extract_bhumipedia_entries(): {len(items)} Q&A")
    for it in items[:5]:
        print("  Q:", it["q"][:78])
        print("  A:", it["a"][:100], "…")
