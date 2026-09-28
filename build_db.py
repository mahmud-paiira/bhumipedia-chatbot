"""Extract Q&A pairs from iLKMS PostgreSQL dump (acts/sections/subsections/schedules/blogs)."""
import html
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SQL_PATH = os.path.join(HERE, "d71_ilkms_5000_dump_2026.08.23.sql")

JUNK_TITLE_RE = re.compile(
    r"^(test|saba|fdfd|asdf|demo|dummy|sample|abc|qwerty|zzz)\b", re.I)
ASCII_JUNK_RE = re.compile(r"^[\w\s.,'()\-]{1,16}$", re.I)
LAW_HINT_RE = re.compile(
    r"আইন|অধ্যাদেশ|বিধিমালা|নীতিমালা|অধিসূচনা|রহদানী|আদেশ|বিধি|act|ordinance|regulation|order\b|rule", re.I)
BENGALI_RE = re.compile(r"[\u0980-\u09FF]")
MAX_ANS = 12000
MAX_VARIANTS = 12

SYN = {
    "ভূমি": ["জমি"],
    "জমি": ["ভূমি"],
    "কর": ["খাজনা"],
    "খাজনা": ["কর"],
    "মৌজা": ["পর্চা"],
    "পর্চা": ["মৌজা"],
    "ম্যাপ": ["নকশা", "মানচিত্র"],
    "নকশা": ["মানচিত্র", "ম্যাপ"],
    "নিবন্ধন": ["রেজিস্ট্রেশন"],
    "আবেদন": ["অনুরোধ"],
}
NUMONLY_RE = re.compile(r"^[\d.।()\s]+$")
DEF_QUOTE_RE = re.compile(r'^\s*[“"\'«]?([^“”"\'«»।;\n]{2,48}[”"\'»]|\S{2,28})\s*(?:অর্থ|মানে|নির্দেশ)\s*[,;।:]')
QUOTED_TERM_RE = re.compile(r'[“"\'«]([^“”"\'«»।\n]{2,40})[”"\'»]')


def _unescape_copy(field):
    if field == r"\N":
        return None
    out = []
    i = 0
    while i < len(field):
        c = field[i]
        if c == "\\" and i + 1 < len(field):
            n = field[i + 1]
            out.append({"n": "\n", "t": "\t", "\\": "\\"}.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_tables(text):
    tables = {}
    cur = None
    for line in text.split("\n"):
        m = re.match(r"^COPY ([\w]+\.[\w]+) \(([^)]+)\) FROM stdin;", line)
        if m:
            tab = m.group(1)
            cols = [c.strip() for c in m.group(2).split(",")]
            tables[tab] = {"cols": cols, "rows": []}
            cur = tab
            continue
        if cur:
            if line == "\\.":
                cur = None
            elif not line.startswith("--"):
                tables[cur]["rows"].append([_unescape_copy(f) for f in line.split("\t")])
    return tables


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", str(s))
    s = html.unescape(s)
    s = re.sub(r"[ \t\u00a0]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s)
    return s.strip()


def good_title(t):
    if not t:
        return False
    t = t.strip()
    if JUNK_TITLE_RE.match(t):
        return False
    if BENGALI_RE.search(t):
        return len(t) >= 12
    if ASCII_JUNK_RE.fullmatch(t):
        return bool(LAW_HINT_RE.search(t))
    return len(t) >= 15


def _clean_num(n):
    if not n:
        return ""
    return re.sub(r"[।.\s]+$", "", n.strip())


ITEM_MARKER_RE = re.compile(
    r"([(（][ক-হ০-৯a-zA-Z]{1,3}[)）])")
ITEM_PRECEDE_RE = re.compile(r"[;।,:—=–-“”\"''‘’`\n]\s*$")
ITEM_CAP = 40
ITEM_MIN = 20


def split_items(content):
    """Split a legal paragraph into clause/item chunks ((ক)… (খ)… / (১)…)."""
    marks = list(ITEM_MARKER_RE.finditer(content))
    if not marks:
        return []
    spans = []
    for m in marks:
        if m.start() > 0 and not ITEM_PRECEDE_RE.search(content[:m.start()]):
            continue
        spans.append((m.start(), m.end()))
    if not spans:
        return []
    end = marks[-1].end() if marks else len(content)
    out = []
    for i, (s, e) in enumerate(spans):
        e2 = spans[i + 1][0] if i + 1 < len(spans) else end
        txt = content[e:e2].strip(" ;,।")
        if len(txt) >= ITEM_MIN:
            out.append((content[s:e], txt))
        if len(out) >= ITEM_CAP:
            break
    return out


def extract_clause_index(content):
    """Return a list of (marker, clause_text) for leading (ক)(খ)… items."""
    marks = list(ITEM_MARKER_RE.finditer(content))
    if not marks:
        return []
    spans = []
    for m in marks:
        if m.start() > 0 and not ITEM_PRECEDE_RE.search(content[:m.start()]):
            continue
        spans.append(m)
    if not spans:
        return []
    end = marks[-1].end() if marks else len(content)
    out = []
    for i, m in enumerate(spans):
        e2 = spans[i + 1].start() if i + 1 < len(spans) else end
        txt = content[m.end():e2].strip(" ;,।")
        if len(txt) >= ITEM_MIN:
            out.append((content[m.start():m.end()], txt))
    return out


def question_variants(head, act=None, num=None):
    h = head.strip("। ").strip()
    if not h or NUMONLY_RE.fullmatch(h):
        return []
    vs = []
    if "?" not in h:
        vs.append(h)
        vs.append(f"{h} কি?")
        vs.append(f"{h} বলতে কি বুঝায়?")
        vs.append(f"{h} সম্পর্কে বিস্তারিত বলো")
        vs.append(f"আমি {h} সম্পর্কে জানতে চাই")
        vs.append(f"{h} সংক্রান্ত বিধান কি?")
        if act:
            dn = f" {num}" if num else ""
            vs.append(f"{act} অনুযায়ী {h} এর বিধান কি?")
            vs.append(f"{act} এর ধারা{dn}: {h} এ কী বলা হয়েছে?")
    else:
        vs.append(h)
        if act:
            vs.append(f"{act} অনুযায়ী {h}")
    if act:
        vs.append(f"{act} নিয়ে {h} সম্পর্কে জানতে চাই")
    for t, alts in SYN.items():
        if t in h:
            for alt in alts:
                if "?" not in h:
                    vs.append(f"{h.replace(t, alt)} কি?")
                else:
                    vs.append(h.replace(t, alt))
    return vs[:MAX_VARIANTS]


FACT_KEYWORDS = {
    "জরিমানা": "এই বিধান অনুযায়ী জরিমানা কত?",
    "কারাদণ্ড": "এই বিধান অনুযায়ী কারাদণ্ড কত?",
    "অনধিক": "সর্বোচ্চ জরিমানা বা সীমা কত?",
    "কত দিন": "কত দিনের সময় বরাদ্দ করা হয়েছে?",
    "মাসের মধ্যে": "কত মাসের মধ্যে করতে হবে?",
    "বছরের মধ্যে": "কত বছরের মধ্যে করতে হবে?",
    "শতাংশ": "এখানে শতাংশ কত?",
}
FACT_CLUE_RE = re.compile(r"(জরিমানা|কারাদণ্ড|অনধিক|কত দিন|মাসের মধ্যে|বছরের মধ্যে|শতাংশ)")


def fact_questions(content, head, act=None):
    """Extract specific, factual Q&A from a legal paragraph (fine/period/percent)."""
    out = []
    seen_sent = set()
    scope = act or head
    for m in FACT_CLUE_RE.finditer(content):
        kw = m.group(1)
        start = max(0, m.start() - 60)
        end = min(len(content), m.end() + 140)
        sentence = content[start:end].strip(" ;,।")
        if len(sentence) < 20 or not re.search(r"[০-৯0-9]|অধিক|মাস|বছর|দিন|টাকা", sentence):
            continue
        if sentence in seen_sent:
            continue
        seen_sent.add(sentence)
        q = FACT_KEYWORDS.get(kw, f"{scope} সম্পর্কিত {kw} বিধান কি?")
        if kw in ("জরিমানা", "কারাদণ্ড", "অনধিক"):
            q = f"{scope} অনুযায়ী {kw} কত?"
        out.append((q, sentence))
    return out[:4]


AMEND_BOILER_RE = re.compile(
    r"(বিলুপ্ত হইল|বিলুপ্তি|প্রতিস্থাপিত হইল|প্রয়োজন হইবে না|প্রতিস্থাপন করা হইবে|কর্তৃক বিলুপ্ত|পরিবর্তে স্থলাভিষিক্ত|—?(ক|খ|গ) টেবিল|সংশোধন|তফসিল প্রতিস্থাপন)")
BOILER_LEN = 140


def section_summary(body, head):
    """Produce a concise, specific, complete headline answer for a section body."""
    first = re.split(r"[।\n]", body)[0].strip(" ;,।") if body else ""
    summ = re.sub(r"\s+", " ", body).strip()
    if len(summ) > 900:
        summ = summ[:900].rstrip() + "…"
    lead = first if first and len(first) >= 15 else ""
    if lead:
        return f"{head}: {lead}।\n\n{summ}"
    return summ


def load_tables_from_sql(path=None):
    """Parse a pg_dump COPY-format file into the {table: {cols, rows}} structure."""
    path = path or SQL_PATH
    text = open(path, encoding="utf-8", errors="replace").read()
    return _parse_tables(text)


def extract_db(tables=None):
    """Build Q&A pairs from a tables dict.

    `tables` is the {schema.table: {cols, rows}} structure. If None, it is
    loaded from the SQL dump file (SQL_PATH), preserving the previous behavior.
    A live PostgreSQL source can pass the same structure via
    db_source.load_tables_from_db().
    """
    if tables is None:
        tables = load_tables_from_sql()
    tb = tables

    def rows(name):
        t = tb.get("public." + name, {"rows": []})
        cols = tb.get("public." + name, {}).get("cols", [])
        ix = {c: i for i, c in enumerate(cols)}
        return t["rows"], ix

    acts, ax = rows("acts_acts")
    secs, sx = rows("acts_sections")
    subs, ux = rows("acts_subsections")
    schs, hx = rows("acts_schedules")
    subschs, ssx = rows("acts_subschedules")
    blogs, bx = rows("blogs_blog")

    sched_by_id = {}
    for r in schs:
        g = lambda k: r[hx[k]] if k in hx and hx[k] < len(r) else None
        sched_by_id[g("id")] = {
            "num": _clean_num(g("number")),
            "heading": g("heading") or "",
            "content": g("content"),
            "sub": g("sub_section_id_id"),
        }

    act_by_id = {}
    for r in acts:
        g = lambda k: r[ax[k]] if ax[k] < len(r) else None
        act_by_id[g("id")] = {
            "title": (g("title_of_act") or "").strip(),
            "year": (g("act_year") or "").strip(),
            "objective": g("objective"),
        }

    sec_by_id = {}
    for r in secs:
        g = lambda k: r[sx[k]] if sx[k] < len(r) else None
        sec_by_id[g("id")] = {
            "num": _clean_num(g("number")),
            "heading": g("heading") or "",
            "content": g("content"),
            "act": g("act_id_id"),
        }

    out = []
    taken = set()

    def add(q, a_raw, act_title=None, more_raw=None):
        a = strip_html(a_raw)
        if len(a) > MAX_ANS:
            a = a[:MAX_ANS].rstrip() + "…"
        if "????" in q or "????" in a:
            return False
        key = re.sub(r"\s+", " ", q.lower()).strip()
        if key in taken and act_title:
            q = f"{q} ({act_title})"
            key = re.sub(r"\s+", " ", q.lower()).strip()
        if key in taken:
            return False
        taken.add(key)
        ent = {"q": q, "a": a, "tpl": False}
        if more_raw is not None:
            more_ans = strip_html(more_raw)
            if more_ans and len(more_ans) > len(a):
                ent["more"] = more_ans[:MAX_ANS].rstrip() + "…" if len(more_ans) > MAX_ANS else more_ans
        out.append(ent)
        return True

    def add_many(qs, a_raw, act_title=None, more_raw=None):
        n = 0
        for q in qs:
            if add(q, a_raw, act_title, more_raw):
                n += 1
        return n

    def good_content(ct):
        return len(ct) >= 25 and "????" not in ct

    def definition_variants(ct_text):
        head = ct_text[:80]
        if "উল্লিখিত" in head and "পরিবর্" in head:
            return []
        terms = []
        m = DEF_QUOTE_RE.match(ct_text)
        if m:
            terms.append(m.group(1).strip("””'\"»•;।,: "))
        for m2 in QUOTED_TERM_RE.finditer(ct_text[:80]):
            if m2.start() == 0 or re.search(
                    r"(?:অর্থ|মানে|নির্দেশ)\s*[,;ঃ:]?\s*$", ct_text[:m2.start()]):
                t2 = m2.group(1).strip()
                if t2 and t2 not in terms:
                    terms.append(t2)
        vs = []
        for t in terms:
            if len(t) < 2 or len(t) > 40 or NUMONLY_RE.fullmatch(t):
                continue
            if re.search(r"[০-৯0-9]|[()]", t) or "অর্থ" in t:
                continue
            vs.append(f"{t} অর্থ কি?")
            vs.append(f"{t} বলতে কি বুঝায়?")
            vs.append(f"{t} কাকে বলে?")
        return vs

    # ---- আইন সমূহ (acts catalog) ---
    def _flag(v, yes="f"):
        return v is not None and v.strip().lower() == yes

    def _int_of(v):
        try:
            return int((v or "").strip())
        except (TypeError, ValueError):
            return 0

    cat_rows = 0
    cat_docs = []
    for r in acts:
        g = lambda k: r[ax[k]] if ax[k] < len(r) else None
        if not _flag(g("is_soft_deleted")) or not _flag(g("is_draft")):
            continue
        if not (g("live") or "").strip().upper() == "YES":
            continue
        t = (g("title_of_act") or "").strip()
        if not good_title(t):
            continue
        typ = (g("ebooks_type") or "").strip()
        if not typ:
            continue
        obj = strip_html(g("objective") or "")
        ok_obj = obj and len(obj) >= 40 and "objective" not in obj.lower() \
            and not ASCII_JUNK_RE.fullmatch(obj) and "????" not in obj
        doc = {
            "title": t, "type": typ, "year": (g("act_year") or "").strip(),
            "pub_date": (g("publication_date") or "").strip(),
            "pub_by": (g("publication_by") or "").strip() or "গেজেট",
            "sections": _int_of(g("total_number_of_sections")),
            "subsections": _int_of(g("total_number_of_sub_sections")),
            "schedules": _int_of(g("total_number_of_schedules")),
            "subschedules": _int_of(g("total_number_of_sub_schedules")),
            "objective": obj if ok_obj else None,
        }
        cat_docs.append(doc)
        t_q = re.sub(r"[।.\s]+$", "", t)
        lines = [t]
        if typ:
            lines.append(f"প্রকারভেদ: {typ}")
        if doc["year"]:
            lines.append(f"সন: {doc['year']} সন")
        if doc["pub_date"]:
            lines.append(f"প্রকাশ: {doc['pub_date']} ({doc['pub_by']})")
        cnt = []
        if doc["sections"]:
            cnt.append(f"{doc['sections']}টি ধারা")
        if doc["subsections"]:
            cnt.append(f"{doc['subsections']}টি উপধারা")
        if doc["schedules"]:
            cnt.append(f"{doc['schedules']}টি তফসিল")
        if doc["subschedules"]:
            cnt.append(f"{doc['subschedules']}টি উপতফসিল")
        if cnt:
            lines.append("গঠন: " + ", ".join(cnt))
        if doc["objective"]:
            lines.append("উদ্দেশ্য: " + doc["objective"])
        ans = "\n".join(lines)
        qs = [t_q, f"{t_q} কি?"]
        qs.append(f"{t_q} সম্পর্কে জানতে চাই")
        if doc["year"]:
            qs.append(f"{t_q} কোন সনে প্রণীত হয়?")
        if doc["pub_date"]:
            qs.append(f"{t_q} কবে প্রকাশিত হয়?")
        if doc["sections"]:
            qs.append(f"{t_q} এ কতটি ধারা আছে?")
            qs.append(f"{t_q} ধারা কতটি?")
        if doc["objective"]:
            qs.append(f"{t_q} এর উদ্দেশ্য কি?")
        cat_rows += add_many(qs, ans)

    # আইন সমূহ overview questions (accurate enumerations from the catalog)
    from collections import Counter
    type_cnt = Counter(d["type"] for d in cat_docs)
    overview_ans = ["ভূমি আইন ও বিধিমালা ডাটাবেসে মোট {}টি দলিল রয়েছে।".format(len(cat_docs))]
    over_lines = []
    for typ, n in type_cnt.most_common():
        rows = [d for d in cat_docs if d["type"] == typ]
        over_lines.append(
            f"{typ} ({n}টি):\n" + "\n".join(f"• {d['title']}" for d in rows))
    block = overview_ans[0] + "\n\n" + "\n\n".join(over_lines)
    cat_rows += add("আইন সমূহ", block)
    cat_rows += add("আইন সমূহ কি কি?", block)
    full_overview = overview_ans[0] + "\n\n" + "\n\n".join(over_lines)
    cat_rows += add_many(
        ["সমুদয় দলিল", "সমুদয় দলিল কি কি?", "সব আইন কি কি?",
         "সবগুলো আইন কি কি?", "সম্পূর্ণ তালিকা দিন", "আইনসমূহের তথ্য দিন"],
        full_overview)
    # enriched type overviews (অধ্যাদেশ, রাষ্ট্রপতির আদেশ)
    enriched = [
        ("অধ্যাদেশ",
         ["অধ্যাদেশসমূহ", "অধ্যাদেশ সমূহ", "অধ্যাদেশ সমূহ কি কি?",
          "অধ্যাদেশ কয়টি আছে?", "অধ্যাদেশগুলো কি কি?",
          "ভূমি সংক্রান্ত অধ্যাদেশ কি কি?"]),
        ("রাষ্ট্রপতির আদেশ",
         ["রাষ্ট্রপতির আদেশসমূহ", "রাষ্ট্রপতির আদেশ সমূহ",
          "রাষ্ট্রপতির আদেশ সমূহ কি কি?", "রাষ্ট্রপতির আদেশ কয়টি?",
          "রাষ্ট্রপতির আদেশ কয়টি আছে?", "রাষ্ট্রপতির আদেশগুলো কি কি?"]),
        ("বিধিমালা",
         ["বিধিমালা সমূহ", "বিধিমালা সমূহ কি কি?", "বিধিমালা কয়টি?",
          "বিধিমালা কয়টি আছে?", "বিধিমালাগুলো কি কি?",
          "ভূমি সংক্রান্ত বিধিমালা কি কি?"]),
        ("নীতিমালা",
         ["নীতিমালা সমূহ", "নীতিমালা সমূহ কি কি?", "নীতিমালা কয়টি?",
          "নীতিমালা কয়টি আছে?", "নীতিমালাগুলো কি কি?",
          "ভূমি সংক্রান্ত নীতিমালা কি কি?"]),
        ("পরিপত্র",
         ["পরিপত্র সমূহ", "পরিপত্র সমূহ কি কি?", "পরিপত্র কয়টি?",
          "পরিপত্র কয়টি আছে?", "পরিপত্রগুলো কি কি?",
          "ভূমি সংক্রান্ত পরিপত্র কি কি?"]),
        ("নির্দেশিকা",
         ["নির্দেশিকা সমূহ", "নির্দেশিকা সমূহ কি কি?", "নির্দেশিকা কয়টি?",
          "নির্দেশিকা কয়টি আছে?", "নির্দেশিকাগুলো কি কি?"]),
        ("ম্যানুয়াল",
         ["ম্যানুয়াল সমূহ", "ম্যানুয়াল সমূহ কি কি?", "ম্যানুয়াল কয়টি?",
          "ম্যানুয়াল কয়টি আছে?", "ম্যানুয়ালগুলো কি কি?"]),
        ("প্রজ্ঞাপন",
         ["প্রজ্ঞাপন সমূহ", "প্রজ্ঞাপন সমূহ কি কি?", "প্রজ্ঞাপন কয়টি?",
          "প্রজ্ঞাপন কয়টি আছে?", "প্রজ্ঞাপনগুলো কি কি?"]),
        ("অন্যান্য",
         ["অন্যান্য সমূহ", "অন্যান্য সমূহ কি কি?", "অন্যান্য কয়টি?",
          "অন্যান্য কয়টি আছে?"]),
    ]
    label_map = {"অন্যান্য": "অন্যান্য (বিবিধ) দলিল"}
    for typ, alias_qs in enriched:
        rows = [d for d in cat_docs if d["type"] == typ]
        if not rows:
            continue
        alias_qs = list(alias_qs) + [f"{typ} সমূহ কয়টি?"]
        lines = []
        for d in rows:
            bits = []
            if d["year"]:
                bits.append(f"{d['year']} সন")
            structure = []
            if d["sections"]:
                structure.append(f"{d['sections']}টি ধারা")
            if d["subsections"]:
                structure.append(f"{d['subsections']}টি উপধারা")
            bits.append(", ".join(structure) if structure else "ধারা বিস্তারিত নেই")
            lines.append(f"• {d['title']} — {', '.join(bits)}")
        ans = (f"ভূমি আইন ডাটাবেসে মোট {len(rows)}টি "
               + f"{label_map.get(typ, typ)} আছে।\n\n" + "\n".join(lines))
        for q in alias_qs:
            cat_rows += add(q, ans)

    key_types = [("আইন", "আইনগুলো")]
    for typ, label in key_types:
        rows = [d for d in cat_docs if d["type"] == typ]
        if not rows:
            continue
        ans = (f"মোট {len(rows)}টি {typ} ডাটাবেসে আছে।\n\n"
               + "\n".join(f"• {d['title']}" for d in rows))
        if label == "আইনগুলো":
            cat_rows += add("ভূমি মন্ত্রণালয়ের আইনগুলো কি কি?", ans)
            cat_rows += add("আইনগুলো কয়টি?", ans)

    # ---- acts: title -> objective (preamble) as answer ---
    act_rows = 0
    for aid, act in act_by_id.items():
        if not good_title(act["title"]):
            continue
        obj = act.get("objective")
        if not obj:
            continue
        ot = strip_html(obj)
        if len(ot) < 40 or "objectiveobjective" in ot.lower():
            continue
        t = act["title"]
        qs = [t, f"{t} কি?", f"{t} আইনটি সম্পর্কে জানতে চাই", f"{t} এর উদ্দেশ্য কি?",
              f"{t} আইন সম্পর্কে বিস্তারিত বলো", f"আমি {t} আইনটি সম্পর্কে জানতে চাই",
              f"{t} আইনটি কি বিষয়ে?"]
        for tt, alts in SYN.items():
            if tt in t:
                qs.append(f"{t.replace(tt, alts[0])} কি?")
        act_rows += add_many(qs, ot)

    # sections: heading variants -> content (+ definition forms) (+ দফা items)
    sec_rows = 0
    for sid, sec in sec_by_id.items():
        act = act_by_id.get(sec["act"])
        if not act or not good_title(act["title"]) or not sec["content"]:
            continue
        ct = strip_html(sec["content"])
        if not good_content(ct):
            continue
        head = sec["heading"].strip("। ") or f"ধারা {sec['num']}"
        boiler = len(ct) <= BOILER_LEN and AMEND_BOILER_RE.search(ct)
        if boiler:
            sec_rows += add(
                f"{act['title']} অনুযায়ী {head} এর বিধান কি?",
                ct, act["title"])
            continue
        qs = question_variants(head, act["title"], sec["num"])
        qs += definition_variants(ct)
        if sec["num"]:
            qs.append(f"{act['title']} এর ধারা {sec['num']} এ কী বলা হয়েছে?")
            qs.append(f"{act['title']} অনুযায়ী ধারা {sec['num']} কি আছে?")
        sec_rows += add_many(qs, ct, act["title"])
        for fq, fa in fact_questions(ct, head, act["title"]):
            sec_rows += add(fq, fa, act["title"], ct)
        sec_rows += add(
            f"{act['title']} অনুযায়ী {head} এর সারসংক্ষেপ",
            section_summary(ct, head), act["title"])
        for marker, itext in extract_clause_index(ct):
            more_text = ct
            sec_rows += add_many(
                [f"{head} এর দফা {marker} এ কী বলা হয়েছে?",
                 f"{marker} দফা বলতে কি বুঝায়?",
                 f"{act['title']} অনুযায়ী {head} এর দফা {marker}",
                 f"{marker} দফায় কি বলা হয়েছে?"],
                itext, act["title"], more_text)

    # subsections: parent heading + sub-number -> content (+ definition forms)
    sub_rows = 0
    for r in subs:
        g = lambda k: r[ux[k]] if ux[k] < len(r) else None
        sec = sec_by_id.get(g("section_id_id"))
        if not sec:
            continue
        act = act_by_id.get(sec["act"])
        if not act or not good_title(act["title"]):
            continue
        c = g("content")
        if not c:
            continue
        ct = strip_html(c)
        if not good_content(ct):
            continue
        num = _clean_num(g("number"))
        own = (g("heading") or "").strip("। ")
        if own:
            head = own
        elif sec["heading"].strip():
            head = f"{sec['heading'].strip('। ')} {num}"
        else:
            head = f"ধারা {sec['num']} {num}".strip()
        qs = question_variants(head, act["title"], f"{sec['num']}{num}".strip())
        qs += definition_variants(ct)
        if num:
            qs.append(f"{act['title']} এর ধারা {sec['num']} উপধারা {num} এ কী বলা হয়েছে?")
            qs.append(f"ধারা {sec['num']} এর উপধারা {num} কি বলে?")
        sub_rows += add_many(qs, ct, act["title"])
        for fq, fa in fact_questions(ct, head, act["title"]):
            sub_rows += add(fq, fa, act["title"], ct)
        sub_rows += add(
            f"{act['title']} অনুযায়ী {head} এর সারসংক্ষেপ",
            section_summary(ct, head), act["title"])
        for marker, itext in extract_clause_index(ct):
            more_text = ct
            sub_rows += add_many(
                [f"{head} এর দফা {marker} এ কী বলা হয়েছে?",
                 f"{head} দফা {marker} বলতে কি বুঝায়?",
                 f"{act['title']} অনুযায়ী {head} এর দফা {marker}",
                 f"{marker} দফায় কি বলা হয়েছে?"],
                itext, act["title"], more_text)

    # schedules (parent chain: schedule -> subsection -> section -> act)
    sched_rows = 0
    for r in schs:
        g = lambda k: r[hx[k]] if hx[k] < len(r) else None
        ss = next((x for x in subs if x[ux["id"]] == g("sub_section_id_id")), None)
        sec = sec_by_id.get(ss[ux["section_id_id"]]) if ss else None
        act = act_by_id.get(sec["act"]) if sec else None
        if not act or not good_title(act["title"]) or not g("content"):
            continue
        ct = strip_html(g("content"))
        if not good_content(ct):
            continue
        num = _clean_num(g("number"))
        base = (g("heading") or "").strip("। ") or f"তফসিল {num}"
        qs = question_variants(base, act["title"], num)
        sched_rows += add_many(qs, ct, act["title"])
        for fq, fa in fact_questions(ct, base, act["title"]):
            sched_rows += add(fq, fa, act["title"], ct)

    # subschedules (chain: subschedule -> schedule -> subsection -> section -> act)
    subsch_rows = 0
    for r in subschs:
        g = lambda k: r[ssx[k]] if k in ssx and ssx[k] < len(r) else None
        sc = sched_by_id.get(g("schedule_id_id"))
        ss = next((x for x in subs if x[ux["id"]] == sc["sub"]), None) if sc else None
        sec = sec_by_id.get(ss[ux["section_id_id"]]) if ss else None
        act = act_by_id.get(sec["act"]) if sec else None
        if not act or not good_title(act["title"]) or not g("content"):
            continue
        ct = strip_html(g("content"))
        if not good_content(ct):
            continue
        unum = _clean_num(g("number"))
        if sc:
            base = ((g("heading") or "").strip("। ")
                    or f"তফসিল {sc['num']} (উপতফসিল {unum})")
            ref = f"{sc['num']}({unum})"
        else:
            base = (g("heading") or "").strip("। ") or f"উপতফসিল {unum}"
            ref = unum
        qs = question_variants(base, act["title"], ref)
        subsch_rows += add_many(qs, ct, act["title"])

    # blog posts
    blog_rows = 0
    blog_titles = []
    blog_by_title = {}
    for r in blogs:
        g = lambda k: r[bx[k]] if bx[k] < len(r) else None
        title = (g("title_name") or "").strip()
        c = g("content")
        if not title or not c or len(title) < 8 or JUNK_TITLE_RE.match(title):
            continue
        ct = strip_html(c)
        if len(ct) < 60 or "????" in ct:
            continue
        blog_titles.append(title)
        blog_by_title.setdefault(title, ct)
        qs = [title, f"{title} সম্পর্কে জানতে চাই", f"{title} বিষয়ে বিস্তারিত বলো"]
        blog_rows += add_many(qs, ct)
    if blog_titles:
        b_ans = (f"ভূমি আইন ডাটাবেসে মোট {len(blog_titles)}টি ব্লগ আছে।\n\n"
                 + "\n".join(f"{i+1}. {t}" for i, t in enumerate(blog_titles)))
        blog_rows += add_many(
            ["ব্লগ সমূহ", "ব্লগ সমূহ কি কি?", "ব্লগ সমূহ কয়টি?",
             "ব্লগ কয়টি আছে?", "ব্লগগুলো কি কি?", "ব্লগের তালিকা দিন"],
            b_ans)

    # ---- descriptive FAQ: natural questions answered by real DB content ----
    faq_rows = 0
    faq_list = []
    fold_bn = lambda s: s.replace("\u09af\u09cd", "\u09df")
    fee_bullets = [
        "নির্ধারিত ফি ছাড়া এক টাকাও নেওয়া যাবে না।",
        "নামজারি আবেদনের সময় আবেদনকারীর প্রথমেই কোর্ট ফি ২০ টাকা এবং নোটিশ ফি ৫০ টাকা মিলিয়ে মোট ৭০ টাকা অনলাইনে প্রদান করতে হবে।",
        "এরপর রেকর্ড সংশোধন ও হালনাগাদকরণের জন্য আবেদনকারীকে ১,০০০ টাকা জমা দিতে হবে।",
        "নামজারীকৃত খতিয়ান সরবরাহ বাবদ প্রতি কপির জন্য ১০০ টাকা নির্ধারণ করা হয়েছে।",
        "অর্থাৎ মোট ১,১৭০ টাকা জমা দিতে হবে, যা ছাড়া এক টাকাও বেশি নেওয়া যাবে না।",
        "অনলাইন কিউআর কোডযুক্ত ডিসিআর কপি পুরোপুরি বৈধ ও আইনসম্মত।",
        "এসিল্যান্ড অফিস ব্যতীত অন্য কোনো দালাল, মহুরি বা উকিলের কাছে নামজারি করা বেআইনি।",
    ]
    faq_src = [
        ("নতুন নির্দেশনা জারি", fee_bullets, [
            "নামজারি ফি", "নামজারী ফি", "নামজারি ফি কত টাকা?", "নামজারি ফি কত?", "নামজারি করতে কত টাকা লাগে?",
            "নামজারির ফি কত?", "নামজারি করার ফি কত?", "নামজারি ফি কি কি?",
            "নামজারিতে মোট কত টাকা দিতে হয়?", "নামজারির ফি নির্ধারণ করা হয়েছে কত?",
            "নামজারি আবেদনের জন্য কত ফি দিতে হয়?", "কোর্ট ফি কত টাকা?",
            "নোটিশ ফি কত টাকা?", "রেকর্ড সংশোধনের ফি কত?",
            "নামজারি খতিয়ানের প্রতি কপির ফি কত?", "নামজারি কি?",
            "ডিসিআর কি?", "ডিসিআর ফি কত?", "ডিসিআর কোথায় জমা দিবো?",
            "ডিসিআর জমা কিভাবে দিবো?", "QR কোডযুক্ত ডিসিআর কি বৈধ?",
            "ডিসিআর কপি কি গ্রহণযোগ্য?", "নামজারিতে কি কি দলিল লাগে?"]),
        ("পরিশোধের আহ্বান", None, [
            "ভূমি উন্নয়ন কর কি?", "খাজনা কি?", "ভূমি উন্নয়ন কর কীভাবে দিবো?",
            "ভূমি উন্নয়ন কর পরিশোধের নিয়ম কি?",
            "ভূমি উন্নয়ন কর অনলাইনে কিভাবে দিবো?",
            "ভূমি উন্নয়ন কর কেন দিতে হয়?", "ভূমি উন্নয়ন কর কিসের জন্য হয়?"]),
        ("৬ ধরনের দলিলে আর টিকবে না জমির মালিকানা", None, [
            "দলিল কি?", "দলিল কত প্রকার?", "জমির মালিকানা কোন দলিলে থাকবে?",
            "কোন দলিলে জমির মালিকানা টিকবে না?"]),
        ("ভূমি (Bhumi) অ্যাপ QR কোড ব্যবহারের অনুরোধ", None, [
            "QR কোড দিয়ে কী যাচাই হয়?", "জাল ডিসিআর চেনার উপায় কি?",
            "ভুয়া খতিয়ান যাচাইয়ের উপায় কি?",
            "ভূমি অ্যাপে QR কোড স্ক্যান করবো কীভাবে?",
            "ভূমি মন্ত্রণালয়ের হটলাইন নম্বর কত?", "ভূয়া দাখিলা চেনার উপায় কি?"]),
        ("অটোমেটেড মিউটেশন সিস্টেম ২.১ ও মোবাইল অ্যাপ", None, [
            "অটোমেটেড মিউটেশন সিস্টেম কি?", "মিউটেশন সিস্টেম ২.১ কি?",
            "নামজারির জন্য উপজেলা ভূমি অফিসে কতবার যেতে হয়?", "ভূমি অ্যাপ কি?"]),
    ]
    for kw, sum_bullets, qs in faq_src:
        body = next((c for t, c in blog_by_title.items() if fold_bn(kw) in fold_bn(t)), None)
        if not body:
            continue
        ans = body
        if sum_bullets and all(x in body for x in sum_bullets):
            ans = ("**সংক্ষেপে:**\n" + "\n".join("• " + x for x in sum_bullets)
                   + "\n\n" + body)
        for q in qs:
            if add(q, ans):
                faq_list.append(q)

    # ---- নামজারি প্রক্রিয়া: step-by-step from verbatim DB sentences ----
    proc_steps = [
        "নামজারি আবেদনের সময় আবেদনকারীর প্রথমেই কোর্ট ফি ২০ টাকা এবং নোটিশ ফি ৫০ টাকা মিলিয়ে মোট ৭০ টাকা অনলাইনে প্রদান করতে হবে।",
        "জমির দলিল যেমন হস্তান্তর দলিল, দাতার বায়া দলিল এবং হালনাগাদ খতিয়ান আবেদনকারী সরাসরি এসিল্যান্ড অফিসে নিয়ে যেতে পারবেন।",
        "নামজারির অনুমোদন হলে এসিল্যান্ড অফিস থেকে মোবাইলে মেসেজ পাঠিয়ে নির্দিষ্ট তারিখে হাজির হতে বলা হবে।",
        "এরপর রেকর্ড সংশোধন ও হালনাগাদকরণের জন্য আবেদনকারীকে ১,০০০ টাকা জমা দিতে হবে।",
        "নামজারীকৃত খতিয়ান সরবরাহ বাবদ প্রতি কপির জন্য ১০০ টাকা নির্ধারণ করা হয়েছে।",
        "অর্থাৎ মোট ১,১৭০ টাকা জমা দিতে হবে, যা ছাড়া এক টাকাও বেশি নেওয়া যাবে না।",
        "এসিল্যান্ড অফিস ব্যতীত অন্য কোনো দালাল, মহুরি বা উকিলের কাছে নামজারি করা বেআইনি।",
    ]
    proc_extra_fee = [
        "আউটসোর্সিং কম্পিউটার অপারেটরের মাধ্যমে আবেদন করা হলেও নির্ধারিত সার্ভিস চার্জ আলাদাভাবে দিতে হবে।",
    ]
    proc_extra_mut = [
        "নামজারির জন্য নাগরিকদের মাত্র একবার উপজেলা ভূমি অফিসে আসতে হবে।",
    ]
    fee_body = next((c for t, c in blog_by_title.items() if fold_bn("নতুন নির্দেশনা জারি") in fold_bn(t)), None)
    mut_body = next((c for t, c in blog_by_title.items() if fold_bn("অটোমেটেড মিউটেশন সিস্টেম ২.১") in fold_bn(t)), None)
    if (fee_body and all(x in fee_body for x in proc_steps)
            and all(x in fee_body for x in proc_extra_fee)
            and mut_body and all(x in mut_body for x in proc_extra_mut)):
        bndig = "০১২৩৪৫৬৭৮৯"
        bn_li = lambda n: "".join(bndig[int(d)] for d in str(n)) + "."
        proc_txt = ("**নামজারি করার ধাপগুলো:**\n\n"
                    + "\n".join(f"{bn_li(i + 1)} {x}" for i, x in enumerate(proc_steps))
                    + "\n\n" + " ".join(proc_extra_mut + proc_extra_fee))
        for q in [
            "নামজারি কীভাবে করবো?", "নামজারি করবো কিভাবে?", "নামজারি কিভাবে হয়?",
            "নামজারি করার নিয়ম কি?", "নামজারি প্রক্রিয়া কি?",
            "নামজারি করার ধাপগুলো কি কি?", "নামজারির জন্য কি কি করতে হয়?",
            "নামজারি আবেদন কোথায় করতে হয়?", "নামজারি অনুমোদনের পর কি করতে হয়?",
        ]:
            if add(q, proc_txt):
                faq_list.append(q)
        faq_list = list(dict.fromkeys(faq_list))
    else:
        print("WARNING: namjari steps verify failed; process questions skipped")
    # ---- খতিয়ান / মৌজা: definitional answers from verbatim DB clauses ----
    khatian_verbatim = (
        '“খতিয়ান” অর্থ State Acquisition and Tenancy Act, 1950 '
        "(Act No. XXVIII of 1951) এর section 143 বা 144 এর অধীন প্রণীত "
        "বা হালনাগাদকৃত বলবৎ সর্বশেষ খতিয়ান;"
    )
    khatian_ctx = (
        "ভূমি-খতিয়ান চূড়ান্তভাবে প্রকাশিত হইবার পর, ভূমি রেকর্ড ও জরীপের "
        "মহা-পরিচালক কর্তৃক এতদুদ্দেশ্যে নির্ধারিত সময়ের মধ্যে রাজস্ব অফিসার "
        "উক্তরূপ চূড়ান্তপ্রকাশনার বিষয় ও উহার তারিখ উল্লেখ করিয়া একটি "
        "প্রত্যায়ন প্রস্তুত করিবেন এবং উহাতে তাঁহার নাম ও সরকারী পদবী "
        "উল্লেখপূর্বক তারিখসহ স্বাক্ষর দান করিবেন"
    )
    khatian_ans = (
        "ভূমি অপরাধ প্রতিরোধ ও প্রতিকার বিধিমালা, ২০২৪ অনুযায়ী:\n\n"
        "• " + khatian_verbatim + "\n\n"
        "অর্থাৎ, খতিয়ান হলো State Acquisition and Tenancy Act, 1950 "
        "(Act No. XXVIII of 1951) এর section 143 বা 144 এর অধীন প্রণীত বা "
        "হালনাগাদকৃত বলবৎ সর্বশেষ খতিয়ান।\n\n"
        "খতিয়ানই হলো ভূমি রেকর্ডের ভিত্তি দলিল—"
        + khatian_ctx
        + "।"
    )

    mazza_verbatim_a = (
        "রাজস্ব অফিসার প্রতিটি মৌজাকে জরীপের একটি একক ধরিয়া উহার অন্তর্গত "
        "রাস্তা-ঘাট, নদী-নালা, বাড়ী-ঘর, মাঠ ও অন্যান্য প্রাকৃতিক বৈশিষ্ট্য "
        "প্রদর্শন করিয়া বড় আকারের একটি ম্যাপ প্রস্তুত করিবেন এবং "
        "প্রস্তুতব্য বা সংশোধনীয় ভূমি-খতিয়ানে সরকার যে সকল বিবরণ লিপিবদ্ধ "
        "করার সিদ্ধান্ত গ্রহণ করেন সেই সকল বিবরণ লিপিবদ্ধ করিবেন"
    )
    mazza_verbatim_b = (
        "যে ক্ষেত্রে কোন মৌজার পূর্ব-নির্ধারিত সীমানাভুক্ত কোন এলাকা জরীপ ও "
        "খতিয়ানের একক হিসাবে অনুপযুক্ত, সেই ক্ষেত্রে রাজস্ব অফিসার যতদূর "
        "সম্ভব স্থানীয়জনগণের মতামত এবং জেলা প্রশাসকের অভিমত যাচাই করিবার "
        "পর জরিপের একক হিসাবে গ্রহণের উদ্দেশ্য এলাকা নির্ধারণের জন্য সরকারের "
        "নিকট, ভূমি রেকর্ড ও জরিপের মহা-পরিচালকের মাধ্যমে, প্রস্তাব পেশ "
        "করিবেন"
    )
    mazza_ans = (
        "ভূমি-খাতয়ান (পাবত্য চট্টগ্রাম) অধ্যাদেশ, ১৯৮৪-এর ভিত্তিতে, মৌজা "
        "হলো ভূমি জরিপের একটি একক।\n\n"
        "• " + mazza_verbatim_a + "।\n\n"
        "সাধারণত কোনো মৌজাকে জরিপের একক হিসেবে ধরা হয়; তবে—\n\n"
        "• " + mazza_verbatim_b + "।"
    )

    kq_khatian = [
        "খতিয়ান কি?", "খতিয়ান মানে কি?", "খতিয়ান কাকে বলে?",
        "খতিয়ান বলতে কি বুঝায়?", "খতিয়ান কী?", "খতিয়ান কি জিনিস?",
        "খতিয়ান কি অর্থ?",
    ]
    kq_mazza = [
        "মৌজা কি?", "মৌজা মানে কি?", "মৌজা কাকে বলে?",
        "মৌজা বলতে কি বুঝায়?", "মৌজা কী?", "মৌজা কি অর্থ?",
    ]
    if "খতিয়ান” অর্থ" in khatian_ans and "মৌজাকে জরীপের একটি একক" in mazza_ans:
        for q in kq_khatian:
            if add(q, khatian_ans):
                faq_list.append(q)
        for q in kq_mazza:
            if add(q, mazza_ans):
                faq_list.append(q)
        faq_list = list(dict.fromkeys(faq_list))
    else:
        print("WARNING: khatian/mazza verification failed; definition questions skipped")

    if faq_list:
        f_ans = (f"ভূমি আইন ডাটাবেসে মোট {len(faq_list)}টি বর্ণনামূলক FAQ আছে।\n\n"
                 + "\n".join(f"{i+1}. {q}" for i, q in enumerate(faq_list)))
        faq_rows += add_many(
            ["বর্ণনামূলক FAQ সমূহ", "FAQ সমূহ", "FAQ কি কি?",
             "বর্ণনামূলক প্রশ্নোত্তর", "সচরাচর জিজ্ঞাসা সমূহ", "FAQ কয়টি?"],
            f_ans)
        fee_qs = [q for q in faq_list if re.search(r"ফি|টাকা|খরচ", q)]
        if fee_qs:
            fee_ans = (f"ভূমি আইন ডাটাবেসে ফি সংক্রান্ত {len(fee_qs)}টি প্রশ্নোত্তর আছে।\n\n"
                       + "\n".join(f"{i+1}. {q}" for i, q in enumerate(fee_qs)))
            faq_rows += add_many(
                ["ফি", "ফি সমূহ", "ফি কি কি?", "ফি কয়টি?", "ফি তালিকা"],
                fee_ans)

    # ---- External PDF corpus (text-layered documents) ----
    try:
        from pdf_source import extract_pdf_entries
        pdf_items = extract_pdf_entries()
        pdf_added = 0
        for it in pdf_items:
            q = it["q"]
            key = re.sub(r"\s+", " ", q.lower()).strip()
            if key in taken:
                continue
            taken.add(key)
            ent = {"q": q, "a": it["a"], "tpl": False}
            if it.get("more"):
                ent["more"] = it["more"]
            out.append(ent)
            pdf_added += 1
        if pdf_added:
            print(f"[pdf_source] added {pdf_added} PDF-derived Q&A")
    except Exception as e:  # PDF corpus is optional; DB core must not fail
        print(f"[pdf_source] integration skipped: {e}")

    # ---- Bhumipedia portal API (live iLKMS: শিরোনাম/বিষয়বস্তু/ধারা/উপধারা/দফা) ----
    try:
        from bhumipedia_source import extract_bhumipedia_entries
        bh_items = extract_bhumipedia_entries()
        bh_added = 0
        for it in bh_items:
            q = it["q"]
            key = re.sub(r"\s+", " ", q.lower()).strip()
            if key in taken:
                continue
            taken.add(key)
            ent = {"q": q, "a": it["a"], "tpl": False}
            if it.get("more"):
                ent["more"] = it["more"]
            out.append(ent)
            bh_added += 1
        if bh_added:
            print(f"[bhumipedia_source] added {bh_added} portal-derived Q&A")
    except Exception as e:  # portal source is optional; DB core must not fail
        print(f"[bhumipedia_source] integration skipped: {e}")

    return out


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    items = extract_db()
    print(f"extract_db(): {len(items)} candidate Q&A")
    for it in items[:3]:
        print("  Q:", it["q"][:80])
        print("  A:", it["a"][:100], "…")
