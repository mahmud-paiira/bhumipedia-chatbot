"""Public read-only dataset APIs.

Reimplements the endpoints documented in QNA_TYPE_APIS.md and
ebook_blog_forum_getApi_chatbot.md against the data this project actually
holds, so the offline chatbot can serve the same contract the live
bhumipedia.land.gov.bd deployment serves:

    GET /api/ebooks/full/            all approved acts + nested tree
    GET /api/blogs/full/             all approved blogs
    GET /api/forums/full/            all approved open groups + topics
    GET /api/v1/qna/type1/           curated service Q&A
    GET /api/v1/qna/type1/<id>/      one row
    GET /api/v1/qna/type2/           full Q&A corpus
    GET /api/v1/qna/type2/<id>/      one row

Shapes were verified field-by-field against the live host; see the module
notes in DEVIATIONS below for the two places this repo cannot match it.

Everything is read-only, unauthenticated and unpaginated except the qna
endpoints, which follow the same rule as the live API: a bare path returns a
plain JSON array, and passing ?page= switches to
{count, next, previous, results}.

Source of truth is the same {table: {cols, rows}} dict that
build_db.load_tables_from_sql() and db_source.load() both produce, so the
endpoints work from either the .sql snapshot or a live database.
"""
import json
import re
import urllib.parse

from qa_dedup import canonical

# Field kind codes. The .sql snapshot and psycopg2 both hand us every value as
# text ("t"/"f", "0", "{a,b}"), so each field declares how to turn it back
# into the JSON type the live API emits.
STR, INT, BOOL, LIST, ISO = "str", "int", "bool", "list", "iso"


def _f(name, kind=STR):
    return (name, kind)


# Order here is the order keys appear in the response. Internal workflow and
# bookkeeping columns (approved, owner, soft-delete stamps, amendment/repeal
# relations, counters on acts) are deliberately absent.
ACT_FIELDS = [
    _f("id", INT), _f("ebooks_type"), _f("act_year"), _f("number"),
    _f("title_of_act"), _f("publication_date"), _f("publication_by"),
    _f("proposal"), _f("objective"), _f("motto"),
    _f("file"), _f("merged_file"), _f("system_generated_pdf"), _f("cover"),
    _f("schedules"), _f("bar_code"),
    _f("created_at_bn"), _f("created_at_en"),
    _f("applicable_date_bn"), _f("applicable_date_en"),
    _f("heading"), _f("branch"), _f("sub_branch"),
    _f("signature_position"), _f("signature_by"), _f("created_by"),
    _f("copy_to"), _f("footer"),
    _f("meta_keywords", LIST), _f("multiple_reference_link", LIST),
    _f("created_date", ISO), _f("sections", LIST),
]

# `note` exists only on sections in this schema; subsections/schedules/
# subschedules have no such column, so they cannot carry it.
SECTION_FIELDS = [
    _f("id", INT), _f("act_id", INT), _f("number"), _f("heading"),
    _f("content"), _f("note"),
    _f("total_number_of_sub_section", INT),
    _f("subsections", LIST), _f("schedules", LIST),
]
SUBSECTION_FIELDS = [
    _f("id", INT), _f("act_id", INT), _f("section_id", INT), _f("number"),
    _f("heading"), _f("content"),
    _f("total_number_of_schedules", INT),
    _f("schedules", LIST),
]
SCHEDULE_FIELDS = [
    _f("id", INT), _f("act_id", INT), _f("section_id", INT),
    _f("sub_section_id", INT), _f("number"), _f("heading"), _f("content"),
    _f("total_number_of_sub_schedules", INT),
    _f("subschedules", LIST),
]
SUBSCHEDULE_FIELDS = [
    _f("id", INT), _f("act_id", INT), _f("section_id", INT),
    _f("sub_section_id", INT), _f("schedule_id", INT),
    _f("number"), _f("heading"), _f("content"),
]

BLOG_FIELDS = [
    _f("id", INT), _f("title_name"), _f("author"), _f("cover"),
    _f("featured", BOOL), _f("content"),
    _f("like_user_counter", INT), _f("share_user_counter", INT),
    _f("viewer_counter", INT), _f("comment_counter", INT),
    _f("created_date", ISO),
]

GROUP_FIELDS = [
    _f("id"), _f("name"), _f("description"), _f("thumbnail"),
    _f("category", INT), _f("badge"), _f("group_type"), _f("featured", BOOL),
    _f("member_count", INT), _f("topic_count", INT),
    _f("created_date", ISO), _f("topics", LIST),
]
TOPIC_FIELDS = [
    _f("id"), _f("group"), _f("title"), _f("description"), _f("thumbnail"),
    _f("status"), _f("is_pinned", BOOL), _f("is_archived", BOOL),
    _f("view_count", INT), _f("reply_count", INT), _f("like_count", INT),
    _f("created_date", ISO),
]

# Column name in this schema -> response key. Django's FK columns are named
# <field>_id, so a FK called `act_id` lands in the dump as `act_id_id`.
_RENAME = {
    "act_id_id": "act_id",
    "section_id_id": "section_id",
    "sub_section_id_id": "sub_section_id",
    "schedule_id_id": "schedule_id",
    "category_id": "category",
    "group_id": "group",
}

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_NULLS = ("", "\\n", "none", "null", "\\N")
_TRUE = ("t", "true", "1", "yes", "y")


# --------------------------------------------------------------------------
# value coercion
# --------------------------------------------------------------------------

def _pg_array(s):
    """Parse a PostgreSQL array literal, or JSON, into a list of strings."""
    t = s.strip()
    if t.startswith("{") and t.endswith("}"):
        out, cur, quoted, esc = [], [], False, False
        for ch in t[1:-1]:
            if esc:
                cur.append(ch); esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                quoted = not quoted
            elif ch == "," and not quoted:
                out.append("".join(cur).strip()); cur = []
            else:
                cur.append(ch)
        out.append("".join(cur).strip())
        return [x for x in out if x]
    if t[0] in "[{":
        try:
            val = json.loads(t)
            if isinstance(val, list):
                return [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
                        for x in val]
            if isinstance(val, dict):
                return [json.dumps(val, ensure_ascii=False)]
        except ValueError:
            pass
    return [t]


def _iso(v):
    """pg_dump writes `2025-09-04 12:26:57.599859+00`; the API emits ISO-8601."""
    s = str(v).strip()
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    m = re.match(r"^(.*[+-]\d{2})$", s)
    if m:
        s = m.group(1) + ":00"
    return s


def _coerce(v, kind):
    if v is None:
        return None
    if kind == LIST:
        s = str(v).strip()
        return None if s in _NULLS else _pg_array(s)
    s = str(v).strip()
    if s in _NULLS:
        return None
    if kind == BOOL:
        return s.lower() in _TRUE
    if kind == INT:
        try:
            return int(s)
        except ValueError:
            try:
                num = float(s)
            except ValueError:
                return None
            return int(num) if num.is_integer() else num
    if kind == ISO:
        return _iso(s)
    return s


def _row(raw):
    """Flatten a {column: text} record into the API's renamed shape."""
    out = {}
    for col, val in raw.items():
        key = _RENAME.get(col, col)
        if key not in out or out[key] is None:
            out[key] = val
    return out


def _project(raw, fields, nested=None):
    """Build the response object, dropping any field whose value is null.

    null-omission is the documented behaviour: two records of the same type can
    end up with different key sets. Empty lists are kept.
    """
    obj = {}
    for name, kind in fields:
        if nested and name in nested:
            val = nested[name]
        else:
            val = _coerce(raw.get(name), kind)
        if val is None:
            continue
        obj[name] = val
    return obj


def _year(v):
    """Bengali-numeral years ('২০২৫') have to become ints to sort by."""
    if v is None:
        return None
    m = re.search(r"\d{4}", str(v).translate(BN_DIGITS))
    return int(m.group(0)) if m else None


def _pos(raw, col):
    """Admin ordering hint; falls back to id so unsorted rows keep insert order."""
    v = _coerce(raw.get(col), INT)
    return (10 ** 9, _coerce(raw.get("id"), INT) or 0) if v is None else (v, _coerce(raw.get("id"), INT) or 0)


# --------------------------------------------------------------------------
# table access
# --------------------------------------------------------------------------

def _table(tables, name):
    t = tables.get("public." + name) or tables.get(name)
    if not t:
        return []
    cols = t["cols"]
    return [_row(dict(zip(cols, r))) for r in t["rows"]]


def _flag(v):
    return str(v).strip().lower() in _TRUE


def _not_deleted(r):
    return not _flag(r.get("is_soft_deleted"))


def _index(rows, *keys):
    out = {}
    for r in rows:
        out.setdefault(tuple(r.get(k) for k in keys), []).append(r)
    return out


# --------------------------------------------------------------------------
# /api/ebooks/full/
# --------------------------------------------------------------------------

def build_full_acts(tables):
    """Every approved act with its sections -> subsections -> schedules ->
    subschedules tree. Child rows are bucketed with dict indexes, so the whole
    listing costs a fixed number of passes regardless of how many acts there
    are (no per-row queries)."""
    acts = [r for r in _table(tables, "acts_acts")
            if _flag(r.get("approved")) and _not_deleted(r) and not _flag(r.get("is_draft"))]
    if not acts:
        return []

    sections = _table(tables, "acts_sections")
    subsections = _table(tables, "acts_subsections")
    schedules = _table(tables, "acts_schedules")
    subschedules = _table(tables, "acts_subschedules")

    act_ids = {a.get("id") for a in acts}
    sec_by_act = _index([s for s in sections if s.get("act_id") in act_ids], "act_id")
    sub_by_sec = _index(subsections, "section_id")
    sch_by_sec = _index([s for s in schedules if s.get("act_id") in act_ids], "section_id")
    sch_by_sub = _index(schedules, "sub_section_id")
    ssch_by_sch = _index(subschedules, "schedule_id")

    def build_schedule(sch):
        kids = [r for r in ssch_by_sch.get((sch.get("id"),), []) if _not_deleted(r)]
        kids.sort(key=lambda r: _pos(r, "sub_schedule_position"))
        return _project(sch, SCHEDULE_FIELDS,
                        {"subschedules": [_project(k, SUBSCHEDULE_FIELDS) for k in kids]})

    def build_subsection(sub):
        kids = [r for r in sch_by_sub.get((sub.get("id"),), []) if _not_deleted(r)]
        kids.sort(key=lambda r: _pos(r, "schedule_position"))
        return _project(sub, SUBSECTION_FIELDS,
                        {"schedules": [build_schedule(s) for s in kids]})

    def build_section(sec):
        subs = [r for r in sub_by_sec.get((sec.get("id"),), []) if _not_deleted(r)]
        subs.sort(key=lambda r: _pos(r, "sub_section_position"))
        # A schedule hangs off the section itself only when it has no
        # subsection parent; otherwise it belongs to the subsection.
        own = [r for r in sch_by_sec.get((sec.get("id"),), [])
               if _not_deleted(r) and r.get("sub_section_id") is None]
        own.sort(key=lambda r: _pos(r, "schedule_position"))
        return _project(sec, SECTION_FIELDS, {
            "subsections": [build_subsection(s) for s in subs],
            "schedules": [build_schedule(s) for s in own],
        })

    out = []
    for act in acts:
        kids = sec_by_act.get((act.get("id"),), [])
        kids = [k for k in kids if _not_deleted(k)]
        kids.sort(key=lambda r: _pos(r, "section_position"))
        out.append(_project(act, ACT_FIELDS,
                            {"sections": [build_section(s) for s in kids]}))

    # act_year desc (nulls last), then publication_date desc. Two stable
    # passes because "nulls last" cannot be expressed by a descending sort.
    out.sort(key=lambda r: str(r.get("publication_date") or ""), reverse=True)
    out.sort(key=lambda r: (_year(r.get("act_year")) is None,
                            -(_year(r.get("act_year")) or 0)))
    return out


# --------------------------------------------------------------------------
# /api/blogs/full/
# --------------------------------------------------------------------------

def build_full_blogs(tables):
    rows = [r for r in _table(tables, "blogs_blog")
            if _flag(r.get("approved")) and _not_deleted(r)]
    rows.sort(key=lambda r: str(r.get("created_date") or ""), reverse=True)
    return [_project(r, BLOG_FIELDS) for r in rows]


# --------------------------------------------------------------------------
# /api/forums/full/
# --------------------------------------------------------------------------

def build_full_forums(tables):
    groups = [g for g in _table(tables, "forum_group")
              if _flag(g.get("approved")) and _not_deleted(g)
              and str(g.get("group_type") or "").strip().lower() == "open"]
    if not groups:
        return []
    ids = {g.get("id") for g in groups}
    # NB: _row() has already renamed the `group_id` column to `group`.
    topics = [t for t in _table(tables, "forum_topic")
              if t.get("group") in ids and _not_deleted(t)]
    by_group = _index(topics, "group")

    out = []
    for g in groups:
        kids = by_group.get((g.get("id"),), [])
        # Topics are included whatever their status; only -is_pinned then
        # -created_date decides order.
        kids.sort(key=lambda r: str(r.get("created_date") or ""), reverse=True)
        kids.sort(key=lambda r: not _flag(r.get("is_pinned")))
        out.append(_project(g, GROUP_FIELDS, {
            "topics": [_project(t, TOPIC_FIELDS) for t in kids],
        }))

    out.sort(key=lambda r: str(r.get("created_date") or ""), reverse=True)
    return out


# --------------------------------------------------------------------------
# /api/v1/qna/type1/ and /type2/
# --------------------------------------------------------------------------

# The live API's category vocabulary, normalised (the live data carries
# trailing spaces and casing variants such as "Khotian"/"khotIan"/" namjari";
# those are collapsed here rather than copied). Each entry is
# (category, keyword, patterns). Order is significant: the first match wins, so
# the specific services are tested before the broad ones.
_QNA_RULES = [
    ("mouja_map", "মৌজা মানচিত্র", ["মৌজা মানচিত্র", "মৌজা ম্যাপ", "মৌজা মানচিত্র", "map of mouza", "mouza map", "মৌজা"]),
    ("vumi_dokhol", "ভূমি দখল", ["ভূমি দখল", "ভূমিদখল", "দখলদার", "দখলকার"]),
    ("vumi_odhigrohon", "অধিগ্রহণ", ["অধিগ্রহণ", "অধিকরণ"]),
    ("jomi_registration", "জমি নিবন্ধন", ["জমি নিবন্ধন", "জমি রেজিস্ট্রেশন", "ভূমি নিবন্ধন", "ভূমি রেজিস্ট্রেশন"]),
    ("jomi_hostantor", "জমি হস্তান্তর", ["হস্তান্তর", "হস্তান্তরপত্র"]),
    ("banton_nama", "বন্টন নাম", ["বন্টন নাম", "বন্টন"]),
    ("dakhila", "দাখিল", ["দাখিল", "জমাদান", "জমা করে", "জমা দিন"]),
    ("khotian", "খতিয়ান", ["খতিয়ান", "খাতিয়ান", "খাটিয়ান", "khatian", "khotian"]),
    ("namjari", "নামজারি", ["নামজারি", "নাম-জারি", "নামদাগ", "namjari"]),
    ("khajna", "খাজনা", ["খাজনা", "খাজানা", "khajna"]),
    ("dolil", "দলিল", ["দলিল", "দলিলপত্র", "দলিল নিবন্ধন", "deeds", "dallil"]),
    ("jorip", "জরিপ", ["জরিপ", "জরীপ"]),
    ("warish", "ওয়ারিশ", ["ওয়ারিশ", "উত্তরাধিকার", "warish", "inheritance"]),
    ("dag", "দাগ", ["দাগ রেজিস্ট্রেশন", "দাগ নম্বর", "দাগ", "mutation"]),
    ("khas", "খাস", ["খাস ভূমি", "খাসভূমি", "খাস"]),
    ("holding", "হোল্ডিং", ["হোল্ডিং", "holding"]),
    ("heba", "হেবা", ["হেবা", "heba"]),
    ("payment", "ফি প্রদান", ["পেমেন্ট", "payment", "অনলাইন পেমেন্ট", "ফি প্রদান", "ফি পরিশোধ"]),
    ("aapil", "আপিল", ["আপিল", "appeal"]),
    ("complain", "অভিযোগ", ["অভিযোগ", "complaint", "complain"]),
    ("review", "রিভিউ", ["রিভিউ", "পুনর্বিবেচনা", "review"]),
    ("nid", "এনআইডি", ["এনআইডি", "nid"]),
    ("jolmohol", "জলমলে", ["জলমলে", "দখলকর্তা"]),
    ("sonod", "সনদ", ["সনদ", "certificate"]),
    ("application", "আবেদন", ["আবেদন", "আবেদনপত্র", "আবেদনের", "application"]),
    ("registration", "নিবন্ধন", ["নিবন্ধন", "রেজিস্ট্রেশন", "register"]),
    ("online", "অনলাইন", ["অনলাইনে", "অনলাইন", "online"]),
    ("case", "মামলা", ["মামলা", "আদালত", "কোর্ট", "court", "case"]),
    ("law", "আইন", ["আইন", "আইনকানুন", "অধ্যাদেশ", "ধারা", "act ", " law", "law"]),
    ("krishi", "কৃষি", ["কৃষি", "কৃষিভূমি", "agriculture"]),
    ("dokhol", "দখল", ["দখল"]),
    ("vumi_seba", "ভূমি সেবা", ["ভূমি সেবা", "ভূমিসেবা", "ভূমি অধিদপ্তর"]),
    ("jomi", "জমি", ["জমি", "ভূমি", "জমির"]),
    ("others", "", []),
]

# type1 on the live API is the small curated set of citizen-service Q&A, while
# type2 is the whole corpus. This repo has one Q&A store rather than the two
# tables the live site has, so type1 is the subset whose question lands in the
# service taxonomy above and type2 is everything. See DEVIATIONS.
SERVICE_CATEGORIES = {c for c, _kw, pats in _QNA_RULES
                      if pats and c not in ("law", "case", "others")}

_NORM = re.compile(r"[^\w\u0980-\u09FF]+")


def _norm_q(s):
    return _NORM.sub(" ", canonical(str(s or "").lower())).strip()


def _classify(question):
    q = _norm_q(question)
    for cat, kw, pats in _QNA_RULES:
        if not pats:
            continue
        for p in pats:
            if p in q or _norm_q(p) in q:
                return cat, kw
    return "others", ""


def _keyword(question, fallback):
    toks = [t for t in _norm_q(question).split() if len(t) > 1]
    return toks[0] if toks else (fallback or None)


def build_qna_rows(dataset):
    """Turn the chatbot's Q&A dataset into API rows.

    Each row is {id, question, answer, category, keyword} with null fields
    omitted. `id` is 1-based and stable for a given dataset build.

    Rows built from the live service carry its own taxonomy in `c`/`k`. That
    label is authoritative and is used as-is; `_classify` is only a fallback
    for the statutory rows the service does not label. Measured against the
    1,336 labelled service questions the keyword rules agree with the service
    just 55.8% of the time, so guessing where a real label exists would make
    the endpoint measurably less accurate than simply reporting what the
    service said.
    """
    out = []
    for i, e in enumerate(dataset, start=1):
        q, a = e.get("q"), e.get("a")
        if not q or not a:
            continue
        cat = e.get("c") or _classify(q)[0]
        kw = e.get("k") or _keyword(q, cat) or cat
        out.append({
            "id": i,
            "question": q,
            "answer": a,
            "category": cat,
            "keyword": kw,
        })
    return out


def qna_type1(rows):
    """The curated service subset that backs /api/v1/qna/type1/."""
    return [r for r in rows if r.get("category") in SERVICE_CATEGORIES]


# --------------------------------------------------------------------------
# pagination (same rule as the live API: only ?page= paginates)
# --------------------------------------------------------------------------

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 1000


def paginate(rows, qs, base_url, path):
    """Return either the plain list or a DRF-shaped page envelope."""
    page_raw = (qs.get("page") or [None])[0]
    if page_raw in (None, ""):
        return rows
    try:
        page = max(1, int(page_raw))
    except (TypeError, ValueError):
        page = 1
    try:
        size = int((qs.get("page_size") or [DEFAULT_PAGE_SIZE])[0])
    except (TypeError, ValueError):
        size = DEFAULT_PAGE_SIZE
    size = max(1, min(MAX_PAGE_SIZE, size))

    total = len(rows)
    start = (page - 1) * size
    results = rows[start:start + size]

    def link(p):
        if p < 1 or (p - 1) * size >= total:
            return None
        q = dict((k, v[0]) for k, v in qs.items() if v)
        q["page"] = str(p)
        q.setdefault("page_size", str(size))
        return "%s%s?%s" % (base_url, path, urllib.parse.urlencode(q))

    return {"count": total, "next": link(page + 1),
            "previous": link(page - 1), "results": results}


# --------------------------------------------------------------------------
# DEVIATIONS from the live deployment
# --------------------------------------------------------------------------
# 1. The live site serves two separate tables (qnData 1,065 rows, QAItem 24,995
#    rows). This repo has neither; it has one built Q&A dataset, so type1 and
#    type2 are two views over it (curated service subset vs everything).
# 2. This repo has no `note` column on subsections/schedules/subschedules, so
#    those nested objects cannot carry the `note` key the docs list.
# 3. Row counts differ because the bundled .sql snapshot is older than the
#    live database (e.g. 130 approved acts here vs 153 live).
