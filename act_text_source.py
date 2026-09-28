"""Q&A from a full local act text (section / subsection / item / schedule).

The portal API and the SQL dump both flatten statutes, so they lose the two
things users actually ask about: a named zone or offence inside a schedule,
and the section that carries a specific number.  This source parses the whole
act text instead, and delegates wording/anchoring to `statute_qa`.

Every answer is copied verbatim from the source text; nothing is generated.
"""

import os
import re

import statute_qa as Q

SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources")

# bdlaws act text: "১|. সংক্ষিপ্ত শিরোনাম, প্রয়োগ ও প্রবর্তন।"
SEC_RE = re.compile(r"^([০-৯0-9]{1,3})\s*(?:\|\s*)?[।.]\s*(.+)$")
SUB_RE = re.compile(r"^\(([০-৯0-9]{1,3})\)\s*(.+)$")
ITEM_RE = re.compile(
    r"^\((ক|খ|গ|ঘ|ঙ|চ|ছ|জ|ঝ|ঞ|ট|ঠ|ড|ঢ|ণ|ত|থ|দ|ধ|ন|প|ফ|ব|ভ|ম|য|র|ল|শ|ষ|স|হ)\)\s*(.+)$")
SCHED_RE = re.compile(r"^\(\s*তফসিল\s*[–—-]?\s*([০-৯0-9]+)?\s*\)")
SCHED_REF_RE = re.compile(r"^\[\s*ধারা[^\]]*\]\s*$")
DEF_RE = re.compile(r"[“\"‘]\s*([^”\"’]{2,60}?)\s*[”\"’]\s*[,;]?\s*অর্থ")
MAX_ANS = 12000


def _join(parts):
    return Q.tidy(" ".join(p for p in parts if p))


def parse_act(text):
    """Split act text into {title, sections[], schedules[], body}.

    sections: [{num, heading, units:[{kind, sub, item, text}]}]
    schedules: [{num, header, rows}]
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    title = Q.tidy(lines[0]) if lines else ""

    sections, schedules = [], []
    cur = None          # current section dict
    unit = None         # current unit dict
    sched = None        # current schedule dict
    sched_lines = None

    for ln in lines[1:]:
        raw = ln.rstrip()
        stripped = raw.strip()

        m = SCHED_RE.match(stripped)
        if m:
            if sched is not None:
                h, rows = Q.split_table("\n".join(sched_lines))
                if h:
                    sched["header"], sched["rows"] = h, rows
            sched = {"num": Q.tidy(m.group(1) or ""), "header": None, "rows": []}
            schedules.append(sched)
            sched_lines = []
            cur, unit = None, None
            continue

        if sched is not None:
            if stripped and not SCHED_REF_RE.match(stripped):
                sched_lines.append(raw)
            elif not stripped:
                sched_lines.append("")
            continue

        m = SEC_RE.match(stripped)
        if m and not ITEM_RE.match(stripped) and not SUB_RE.match(stripped):
            # "২|. সংজ্ঞা।——বিষয় বা প্রসঙ্গের পরিপন্থি কোনো কিছু না থাকিলে, এই আইনে,"
            # keeps only "সংজ্ঞা" as the heading; the tail is body text.
            parts = re.split(r"[।]", m.group(2), maxsplit=1)
            cur = {"num": Q.tidy(m.group(1)),
                   "heading": Q.tidy(parts[0]).strip("।. "),
                   "units": []}
            sections.append(cur)
            unit = None
            if len(parts) > 1 and parts[1].strip():
                unit = {"kind": "sub", "sub": "", "item": "",
                        "text": parts[1].strip()}
                cur["units"].append(unit)
            continue

        if cur is None:
            continue

        m = SUB_RE.match(stripped)
        if m:
            unit = {"kind": "sub", "sub": Q.tidy(m.group(1)),
                    "item": "", "text": m.group(2)}
            cur["units"].append(unit)
            continue

        m = ITEM_RE.match(stripped)
        if m:
            unit = {"kind": "item", "sub": unit["sub"] if unit else "",
                    "item": Q.tidy(m.group(1)), "text": m.group(2)}
            cur["units"].append(unit)
            continue

        if unit is not None and stripped:
            unit["text"] = _join([unit["text"], stripped])
        elif stripped:
            unit = {"kind": "sub", "sub": "", "item": "", "text": stripped}
            cur["units"].append(unit)

    if sched is not None and sched["header"] is None:
        h, rows = Q.split_table("\n".join(sched_lines or []))
        if h:
            sched["header"], sched["rows"] = h, rows

    body_end = text.find("\n(তফসিল")
    if body_end < 0:
        body_end = len(text)
    return {
        "title": title,
        "sections": sections,
        "schedules": schedules,
        "body": text[:body_end],
        "full": text,
    }


def _scope(act, label):
    return f"{act} এর {label}" if label else f"{act} আইন"


def _label_for(sec, unit):
    if unit["kind"] == "item":
        base = f"ধারা {sec['num']}"
        if unit["sub"]:
            base += f"({unit['sub']})"
        return f"{base} এর {unit['item']} উপধারা"
    if unit["kind"] == "sub" and unit["sub"]:
        return f"ধারা {sec['num']}({unit['sub']})"
    return f"ধারা {sec['num']}"


def extract_act_qa(text, cap_per_unit=14):
    """All (question, answer, is_template) triples for one act text."""
    act = parse_act(text)
    title = act["title"]
    if not title:
        return []

    out = []
    seen = set()

    def push(q, a, tpl=False):
        q, a = Q.tidy(q), Q.tidy(a)
        if not q or not a or len(a) < 12:
            return
        k = Q.squash(q)
        if k in seen:
            return
        seen.add(k)
        out.append((q, a[:MAX_ANS].rstrip() + "…" if len(a) > MAX_ANS else a, tpl))

    # --- act level ---
    for q, a in Q.structural_qa(act["body"], title, act=title, cap=14):
        push(q, a)
    push(f"{title} আইনটি কোন বিষয়ে প্রণীত হয়েছে?",
         _objective(act["body"], title))

    # --- sections / subsections / items ---
    for sec in act["sections"]:
        body = " ".join(u["text"] for u in sec["units"])
        sec_text = _join([sec["heading"], body])
        if sec_text:
            push(f"{title} আইনের ধারা {sec['num']} কী বিধান করে?", sec_text)
        for q, a in Q.statute_facts(sec_text, _scope(title, f"ধারা {sec['num']}"),
                                    cap=cap_per_unit):
            push(q, a)
        _short_fact_aliases(push, sec, sec_text)

        for u in sec["units"]:
            label = _label_for(sec, u)
            body_u = Q.tidy(u["text"])
            if len(body_u) < 20:
                continue
            if u["kind"] == "item":
                q = f"{title} আইনের {label}-এ কী বিধান করা হয়েছে?"
            else:
                q = f"{title} আইনের {label} কী বিধান করে?"
            push(q, body_u)
            for q2, a2 in Q.statute_facts(body_u, _scope(title, label),
                                          cap=cap_per_unit):
                push(q2, a2)
            for term, defn in _definitions(body_u):
                push(f"{title} আইনে “{term}” বলতে কী বোঝায়?",
                     _def_answer(defn, term))
                push(f"{title} আইনে “{term}” এর সংজ্ঞা কী?", _def_answer(defn, term))
                push(f"“{term}” কাকে বলে?", _def_answer(defn, term))

    # --- schedules ---
    for sc in act["schedules"]:
        if not sc["header"] or not sc["rows"]:
            continue
        label = f"তফসিল-{sc['num']}" if sc["num"] else "তফসিল"
        for q, a in Q.table_qa(sc["header"], sc["rows"], title, label):
            push(q, a)
        _short_schedule_aliases(push, title, sc, label)

    return out


# A schedule row is anchored by a code ("AZ") or by its own name, so a short
CODE_RE = re.compile(r"^[A-Z][A-Z/]{1,7}$")

# The long form anchors a number on the section label ("ধারা ৭(৫) অনুযায়ী
# কত শতাংশ?"), which no user types.  These subject-led short forms recover the
# headline limits.  Each subject is specific to this act, so they cannot be
# answered with another act's figure.
SHORT_FACT_ALIASES = (
    (re.compile(r"অনধিক\s*[০-৯0-9][^।]{0,40}?শতাংশ"),
     ("কৃষিভূমি অকৃষি কাজে ব্যবহারে সর্বোচ্চ কত শতাংশ ব্যবহার করা যাবে?",
      "কৃষিভূমি অকৃষি কাজে সর্বোচ্চ কত শতাংশ?")),
    (re.compile(r"অন্তর\s*অন্তর"),
     ("জোনিং ম্যাপ কত বছর পরপর হালনাগাদ করা হবে?",
      "জোনিং ম্যাপ কত বছর পরপর হালনাগাদ?")),
    (re.compile(r"কার্যদিবস"),
     ("জোনিং ম্যাপ প্রণয়নে সরকারকে কতদিন সময় দেওয়া হয়েছে?",
      "জোনিং ম্যাপ প্রণয়নে কতদিন সময় দেওয়া হয়েছে?")),
)


def _sentence_with(text, m):
    """The danda-delimited sentence containing match `m`."""
    sents = [s for s in re.split(r"(?<=।)\s*", text or "") if s.strip()]
    for s in sents:
        if m.group(0) in s:
            return Q.tidy(s)
    return Q.tidy(text)


def _short_fact_aliases(push, sec, sec_text):
    # Non-template on purpose: "কত শতাংশ" / "কত বছর" are plain factual asks
    # with no intent word (দণ্ড/ফি/আবেদন), so the template gate would drop them.
    for rx, questions in SHORT_FACT_ALIASES:
        m = rx.search(sec_text or "")
        if not m:
            continue
        ans = _sentence_with(sec_text, m)
        for q in questions:
            push(q, ans)


def _bn_name(name):
    """'কৃষি অঞ্চল (Agricultural Zone)' -> 'কৃষি অঞ্চল'."""
    return Q.tidy(re.sub(r"\s*\([^)]*\)", "", name or ""))


def _short_schedule_aliases(push, title, sc, label):
    header, rows = sc["header"], sc["rows"]
    i_code = Q._col(header, "কোড", "code", "সংকেত")
    i_name = Q._col(header, "জোনের নাম", "অপরাধের বর্ণনা", "বিষয়ের নাম",
                    "নাম", "বিষয়", "বর্ণনা")
    if i_name < 0:
        i_name = 0
    i_desc = Q._col(header, "জোনের বর্ণনা", "বর্ণনা", "বিবরণ")
    if i_desc == i_name:
        i_desc = -1
    i_dan = Q._col(header, "আরোপণীয় দণ্ড", "দণ্ড", "শাস্তি")

    for r in rows:
        if len(r) <= i_name or not r[i_name]:
            continue
        name = r[i_name]
        bn = _bn_name(name) or name
        # A code -> name lookup is a plain factual question, so these stay
        # non-template: templates are gated on an intent word (দণ্ড/শাস্তি/ফি)
        # appearing in the user's query, which "AZ জোন কোনটি?" never carries.
        if i_code >= 0 and len(r) > i_code and CODE_RE.match(r[i_code] or ""):
            code = r[i_code]
            push(f"{code} কোডটি কোন জোন বা বিষয়?", name)
            push(f"{code} কোডের জোন কোনটি?", name)
            push(f"{code} জোন কোনটি?", name)
            push(f"{bn} জোনের কোড কী?", code)
        if i_desc >= 0 and len(r) > i_desc and len(r[i_desc]) > 14:
            push(f"{bn} কোন বিষয়?", r[i_desc])
        if i_dan >= 0 and len(r) > i_dan and len(r[i_dan]) > 8:
            push(f"{bn} এর শাস্তি বা দণ্ড কত?", r[i_dan], tpl=True)

    n = len(rows)
    what = "জোন" if i_code >= 0 and i_code > i_name else "অপরাধ"
    push(f"{label}-এ মোট কয়টি {what} চিহ্নিত করা হয়েছে?",
         f"{label}-এ মোট {Q.bn_num(n)}টি {what} চিহ্নিত করা হয়েছে।")

    # The cognizability columns are constant across rows, so the long form is a
    # single aggregate question.  Repeat it without the act title, which is what
    # a user actually types; the answer keeps the act+schedule prefix so it
    # still says which statute it came from.
    for idx, word in ((Q._col(header, "আমলযোগ্যতা", "আমল"), "আমলযোগ্য"),
                      (Q._col(header, "জামিনযোগ্যতা", "জামিন"), "জামিনযোগ্য"),
                      (Q._col(header, "আপোষযোগ্যতা", "আপোষ"), "আপোষযোগ্য")):
        if idx < 0:
            continue
        vals = {r[idx] for r in rows if len(r) > idx and r[idx]}
        if len(vals) != 1:
            continue
        only = next(iter(vals))
        push(f"কোনগুলো {word}?",
             f"{title} এর {label}-এর সব ক্ষেত্রে এই মানটি প্রযোজ্য: {only}। "
             f"সংশ্লিষ্ট {Q.bn_num(n)}টি বিষয়: "
             + "; ".join(_bn_name(r[i_name]) for r in rows
                         if len(r) > i_name and r[i_name]))


def _objective(body, title):
    m = re.search(r"(এতদ্বারা নিম্নরূপ আইন করা হইল|এতদ্ভাবে আইন করা হইল)", body)
    if m:
        head = body[: m.start()]
        seg = head.strip()
        for sep in ("যেহেতু", "সেহেতু"):
            i = seg.rfind(sep)
            if i > 200:
                seg = seg[i + len(sep):]
        seg = Q.tidy(seg)
        if len(seg) > 60:
            return f"{title} আইনের উদ্দেশ্য: {seg[:1200]}"
    return f"{title} সংক্রান্ত আইন।"


def _definitions(text):
    out = []
    for m in DEF_RE.finditer(text or ""):
        term = Q.tidy(m.group(1))
        if len(term) < 2 or re.search(r"[০-৯0-9()]", term):
            continue
        # definition runs to the next ";"/","-terminated clause or a new item
        tail = text[m.start():]
        cut = re.search(r"[;।]|\s\([ক-হ]\)\s|,\s*\(?[০-৯0-9]{0,2}\)?\s*(?:ইহা|এই|উক্ত)\b", tail)
        defn = Q.tidy(tail[: cut.start()] if cut else tail)
        if len(defn) < 20:
            continue
        if not any(t == term for t, _ in out):
            out.append((term, defn))
    return out


def _def_answer(defn, term):
    """`defn` already reads '“term” অর্থ …'; only prefix when it does not."""
    d = Q.tidy(defn)
    if d.startswith("“") or d.startswith('"'):
        return d
    bare = d.lstrip()
    if bare.startswith(term):
        return d
    return Q.tidy(f"“{term}” অর্থ {d}")


def extract_act_entries(path=None, cap_per_unit=14):
    """[{'q', 'a', 'tpl'}] for every act text under `sources/`."""
    items = []
    if path:
        files = [path]
    else:
        files = []
        if os.path.isdir(SOURCE_DIR):
            for fn in sorted(os.listdir(SOURCE_DIR)):
                if fn.lower().endswith((".txt", ".md")):
                    files.append(os.path.join(SOURCE_DIR, fn))
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if not text.strip():
            continue
        try:
            for q, a, tpl in extract_act_qa(text, cap_per_unit=cap_per_unit):
                items.append({"q": q, "a": a, "tpl": bool(tpl)})
        except Exception as e:  # one bad file must not break the build
            print(f"[act_text_source] skipped {os.path.basename(f)}: {e}")
    return items
