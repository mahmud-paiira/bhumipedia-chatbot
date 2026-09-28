"""Structural Q&A extraction for statutory text.

The generic template generator (`build_db.question_variants`) only ever
re-asks a section's own words, so it cannot answer questions about the
*values* a statute fixes.  This module adds question types anchored to a
concrete fact instead of a heading, which is what users actually ask:

  * money amounts        -> "এই ধারায় কত টাকা অর্থদণ্ড? (২ (দুই) লক্ষ টাকা)"
  * percentages          -> "কত শতাংশ কৃষিভূমি অকৃষি কাজে ব্যবহার করা যাবে না?"
  * deadlines/periods    -> "কত কার্যদিবসের মধ্যে আপত্তি দাখিল করতে হবে?"
  * punishments          -> "কত মাস কারাদণ্ড?"
  * তফসিল tables         -> one Q&A per table row (zone, offence, ...)
  * scope/effect/repeal  -> "এই আইন কোথায় প্রযোজ্য?", "কবে কার্যকর?", "কী রহিত?"

Every value is copied verbatim from the source; nothing is invented.
The patterns target real Bengali drafting idioms, which the earlier
`FACT_CLUE_RE` missed entirely: it looked for "শতাংশ" where acts write
"শতকরা ১০ (দশ) ভাগ", and for "কত দিন" where acts write
"৩০ (ত্রিশ) কার্যদিবসের মধ্যে".
"""

import re

BN = "\u09e6\u09e7\u09e8\u09e9\u09ea\u09eb\u09ec\u09ed\u09ee\u09ef"
DIGITS = {
    "\u09e6": "0", "\u09e7": "1", "\u09e8": "2", "\u09e9": "3", "\u09ea": "4",
    "\u09eb": "5", "\u09ec": "6", "\u09ed": "7", "\u09ee": "8", "\u09ef": "9",
}
TRANS = str.maketrans(DIGITS)
NUM = "[\u09e6-\u09ef0-9]"

DANDA = "\u0964"
MONTHS = "কার্যদিবস|বৎসর|বছর|মাস|সপ্তাহ|দিন|ঘণ্টা"
MONEY_UNIT = "টাকা|লক্ষ|লাখ|কোটি|হাজার"


def to_ascii_digits(s):
    return s.translate(TRANS)


_BN_DIGITS = "\u09e6\u09e7\u09e8\u09e9\u09ea\u09eb\u09ec\u09ed\u09ee\u09ef"


def bn_num(n):
    """Render an int in Bengali digits, which is what a gazette uses."""
    return str(n).translate(str.maketrans("0123456789", _BN_DIGITS))


def tidy(s):
    return re.sub(r"\s+", " ", s or "").strip(" \t;,|" + DANDA)


def squash(s):
    return re.sub(r"\s+", "", s or "")


def value_label(num, word, unit):
    """Render a statutory amount the way the gazette writes it: '১০ (দশ) বৎসর'."""
    num = tidy(num).rstrip(".,")
    word = tidy(word)
    if word:
        head = f"{num} ({word})" if num else word
    else:
        head = num
    return f"{head} {unit}".strip()


def punish_unit(m):
    """'৬ (ছয়) মাস বিনাশ্রম কারাদণ্ড' -> '৬ (ছয়) মাস বিনাশ্রম কারাদণ্ড' label tail."""
    unit = tidy(m.group(3) or "")
    vin = re.sub(r"\s+", " ", (m.group(4) or "")).strip()
    kind = m.group(5) or "কারাদণ্ড"
    return " ".join(p for p in (unit, vin, kind) if p)


def _digits_ok(num):
    return bool(to_ascii_digits(num or "").strip(".,"))


# --- value patterns ---------------------------------------------------------
# NB: these are f-strings, so every literal `{n,m}` quantifier is doubled.
AMT_RE = re.compile(
    rf"({NUM}[{BN}0-9.,]{{0,14}}?)\s*(?:/\-\s*)?(?:\(([^)]{{1,30}})\)\s*)?"
    rf"({MONEY_UNIT})"
)
AMMONY_RE = re.compile(
    rf"(অনধিক\s*)?({NUM}[{BN}0-9.,]{{0,14}}?)\s*(?:/\-\s*)?(?:\(([^)]{{1,30}})\)\s*)?"
    rf"({MONEY_UNIT})"
)
DUR_RE = re.compile(
    rf"({NUM}[{BN}0-9.,]{{0,8}}?)\s*(?:\(([^)]{{1,30}})\)\s*)?({MONTHS})"
)
PCT_RE = re.compile(
    rf"({NUM}[{BN}0-9.,]{{0,8}}?)\s*(?:\(([^)]{{1,20}})\)\s*)?(শতাংশ|ভাগ|শতকরা|%)"
)
RECUR_RE = re.compile(
    rf"প্রতি\s*({NUM}[{BN}0-9.,]{{0,8}}?)\s*(?:\(([^)]{{1,20}})\)\s*?)?"
    rf"({MONTHS})\s*অন্তর"
)
PUNISH_RE = re.compile(
    rf"({NUM}[{BN}0-9.,]{{0,8}}?)\s*(?:\(([^)]{{1,24}})\)\s*)?"
    rf"({MONTHS})?\s*(বিনাশ্রম\s*)?(কারাদণ্ডসহ|কারাদণ্ড)"
)
DEADLINE_HINT = re.compile(
    r"(মধ্যে|পরে|পূর্বে|আগে|সময়সীমার?\s*মধ্যে|সময়ের\s*মধ্যে|অবধি|পর্যন্ত)"
)
FINE_TAIL = re.compile(r"(অর্থদণ্ড|জরিমানা|দণ্ড|অব্যাহতি)")

# --- sentence-aligned windows ----------------------------------------------
BOUND = re.compile(r"।|\n")


def _window(text, start, end, extra=0):
    """Return whole sentences covering [start,end), never a mid-word cut."""
    lo = 0
    for m in BOUND.finditer(text, 0, start):
        lo = m.end()
    hi = len(text)
    for m in BOUND.finditer(text, end):
        hi = m.start() + 1
        break
    if extra:
        n = 0
        for m in BOUND.finditer(text, hi):
            n += 1
            if n > extra:
                break
            hi = m.start() + 1
    return tidy(text[lo:hi]).strip(" ,;")


# --- generic fact extraction ------------------------------------------------
def statute_facts(text, scope, cap=12):
    """Yield (question, answer) for every distinct value fixed by `text`.

    Each question embeds the value so that a section fixing several numbers
    yields several *distinct* questions, instead of the single generic
    "জরিমানা কত?" that used to collapse to ~47 entries corpus-wide.
    """
    if not text:
        return []
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    out, seen = [], set()
    scope = tidy(scope) or "এই বিধান"

    def push(q, a):
        a = tidy(a)
        if len(a) < 15 or len(q) < 8:
            return
        k = (squash(q), squash(a)[:160])
        if k in seen:
            return
        seen.add(k)
        out.append((q, a))

    # 1) fines / money attached to a punishment word -------------------
    amn_spans = []
    for m in AMMONY_RE.finditer(text):
        if not _digits_ok(m.group(2)):
            continue
        tail = text[m.end():m.end() + 16]
        if not FINE_TAIL.search(tail) and not m.group(1):
            continue
        amn_spans.append(m.span())
        val = value_label(m.group(2), m.group(3), m.group(4))
        push(f"{scope} অনুযায়ী জরিমানা বা অর্থদণ্ড কত? ({val})",
             _window(text, m.start(), m.end()))
    amn_spans = [s for s in amn_spans if s[1] - s[0] > 3]

    # 2) plain amounts that are NOT fines (fees, deposits, amounts) ----
    for m in AMT_RE.finditer(text):
        if not _digits_ok(m.group(1)):
            continue
        if any(s[0] <= m.start() < s[1] for s in amn_spans):
            continue
        tail = text[m.end():m.end() + 16]
        if FINE_TAIL.search(tail):
            continue
        val = value_label(m.group(1), m.group(2), m.group(3))
        push(f"{scope} অনুযায়ী কত টাকা বা অঙ্কের কথা বলা হয়েছে? ({val})",
             _window(text, m.start(), m.end()))

    # 3) imprisonment -------------------------------------------------
    for m in PUNISH_RE.finditer(text):
        if not _digits_ok(m.group(1)):
            continue
        val = value_label(m.group(1), m.group(2), punish_unit(m))
        push(f"{scope} অনুযায়ী কারাদণ্ড কত? ({val})",
             _window(text, m.start(), m.end()))

    # 4) percentage ---------------------------------------------------
    for m in PCT_RE.finditer(text):
        if not _digits_ok(m.group(1)):
            continue
        unit = "শতাংশ" if m.group(3) == "ভাগ" else m.group(3)
        val = value_label(m.group(1), m.group(2), unit)
        push(f"{scope} অনুযায়ী কত শতাংশ? ({val})",
             _window(text, m.start(), m.end()))

    # 5) recurring cycles ----------------------------------------------
    rec_spans = []
    for m in RECUR_RE.finditer(text):
        if not _digits_ok(m.group(1)):
            continue
        rec_spans.append(m.span())
        val = value_label(m.group(1), m.group(2), m.group(3))
        push(f"{scope} অনুযায়ী কত {m.group(3)} অন্তর অন্তর? ({val})",
             _window(text, m.start(), m.end()))

    # 6) durations / deadlines -----------------------------------------
    for m in DUR_RE.finditer(text):
        if not _digits_ok(m.group(1)):
            continue
        if any(s[0] <= m.start() < s[1] for s in rec_spans):
            continue
        unit = m.group(3)
        val = value_label(m.group(1), m.group(2), unit)
        left = text[max(0, m.start() - 46):m.start()]
        if DEADLINE_HINT.search(left):
            push(f"{scope} অনুযায়ী কত {unit}-এর মধ্যে সময়সীমা? ({val})",
                 _window(text, m.start(), m.end()))
        elif unit in ("বৎসর", "বছর", "মাস", "সপ্তাহ"):
            push(f"{scope} অনুযায়ী কত {unit}? ({val})",
                 _window(text, m.start(), m.end()))
    return out[:cap]


# --- structural question types ---------------------------------------------
EFFECTIVE_RE = re.compile(
    r"[^।\n]{0,110}(?:অবিলম্বে\s*কার্যকর|সনের[^।\n]{0,40}থেকে[^।\n]{0,30}কার্যকর"
    r"|কার্যকর\s*হইবে|কার্যকর\s*হইবার\s*পর|কার্যকর\s*হইবার\s*তারিখে)[^।\n]{0,90}।"
)
NOT_APPLY_RE = re.compile(
    r"[^।\n]{0,150}(?:ব্যতীত|বাদে)[^।\n]{0,70}প্রযোজ্য[^।\n]{0,70}।"
)
APPLY_RE = re.compile(
    r"[^।\n]{0,150}(?:সমগ্র\s*বাংলাদেশে|এই\s*আইন[^।\n]{0,60})?[^।\n]{0,40}প্রযোজ্য\s*হইবে[^।\n]{0,80}।"
)
REPEAL_RE = re.compile(
    r"[^।\n]{0,170}(?:অধ্যাদেশ|আইন|কার্যবিধি|বিধিমালা)[^।\n]{0,70}"
    r"রহিত\s*করা\s*হইল[^।\n]{0,70}।"
)
PREFERENCE_RE = re.compile(
    r"[^।\n]{0,160}(?:ভিন্নতর\s*যাহা\s*কিছুই\s*থাকুক\s*না\s*কেন"
    r"|এই\s*আইনের\s*বিধানাবলি\s*প্রযোজ্য)[^।\n]{0,110}।"
)
DELEGATION_RE = re.compile(
    r"[^।\n]{0,40}ক্ষমতা\s*অর্পণ[^।\n]{0,10}\n?[^।\n]{0,220}।"
)
ITEM_MARK = re.compile(r"\((?:ক|খ|গ|ঘ|ঙ|চ|ছ|জ|ঝ|ঞ)\)")
# section heading; bdlaws text uses "১|. সংক্ষিপ্ত শিরোনাম" (danda + pipe),
# some gazette copies drop the pipe and use a bare "৭। মৌলিক ফসল"
SECTION_MARK = re.compile(r"(?m)^[ \t]*([০-৯0-9]{1,3})\s*(?:\|\s*)?[।.]\s*[ঀ-৿]")
# the schedule itself starts at a line-leading "(তফসিল-১)"; in-text references
# such as "তফসিল-১ অনুযায়ী জোনিং করিবে" must not truncate the act body
SCHEDULE_HEAD = re.compile(r"(?m)^[ \t]*\([ \t]*তফসিল")


def _section_sequence(body):
    """Section numbers forming a strictly ascending 1,2,3,... run.

    Schedule tables restart numbering at 1 ("১। অনুমোদন ব্যতীত ...") and
    subsection bodies can begin with a bare numeral, so a naive scan over the
    whole act over-counts.  Keeping the ascending run that starts at the first
    "১" yields the real section list.
    """
    out = []
    for n in SECTION_MARK.findall(body or ""):
        d = to_ascii_digits(n).strip(".,")
        if not d.isdigit():
            continue
        d = int(d)
        if not out:
            if d == 1:
                out = ["১"]
            continue
        if d == int(to_ascii_digits(out[-1]).strip(".,")) + 1:
            out.append(n)
    return out


def structural_qa(text, scope, act=None, cap=10):
    """Scope / effect / repeal / precedence questions for an act or a section."""
    if not text:
        return []
    out, seen = [], set()
    scope = tidy(scope) or "এই আইন"
    who = scope if scope != (act or "") else f"{scope} আইন"

    def push(q, a):
        a = tidy(a)
        # a bare heading like "১২|. ক্ষমতা অর্পণ" carries no information
        if len(a) < 18 or squash(a) in seen or a == scope:
            return
        seen.add(squash(a))
        out.append((q, a))

    for rx, q in (
        (EFFECTIVE_RE, f"{who} কবে কার্যকর হইবে?"),
        (NOT_APPLY_RE, f"{who} কোথায় প্রযোজ্য নয়?"),
        (APPLY_RE, f"{who} কোথায় বা কোন ক্ষেত্রে প্রযোজ্য?"),
        (REPEAL_RE, f"{who} কোন আইন বা অধ্যাদেশ রহিত করা হয়েছে?"),
        (PREFERENCE_RE, f"{who} অন্য আইনের সাথে কোনটির প্রাধান্য?"),
        (DELEGATION_RE, f"{who} ক্ষমতা অর্পণের বিধান কী?"),
    ):
        m = rx.search(text)
        if m:
            push(q, m.group(0))

    body = text
    sm = SCHEDULE_HEAD.search(text)
    if sm:
        body = text[: sm.start()]

    secs = _section_sequence(body)
    if len(secs) >= 2:
        push(f"{who} মোট কয়টি ধারা রয়েছে?",
             f"{who} এ মোট {bn_num(len(secs))}টি ধারা রয়েছে; "
             f"সর্বোচ্চ ধারা নম্বর {secs[-1]}। ধারাগুলো: {' '.join(secs)}")

    marks = ITEM_MARK.findall(text)
    if len(marks) >= 2:
        uniq = []
        for m in marks:
            if m not in uniq:
                uniq.append(m)
        push(f"{who} এ মোট কয়টি গ্রন্থসূচী আইবদ্ধ উপধারা রয়েছে?",
             f"{who} এ মোট {bn_num(len(marks))}টি গ্রন্থসূচী আইবদ্ধ উপধারা রয়েছে; "
             f"সর্বোচ্চ উপধারা {uniq[-1]}। উপধারাগুলো: {' '.join(uniq)}")
    return out[:cap]


# --- তফসিল / table extraction ---------------------------------------------
CELL_SPLIT = re.compile(r"\s*\|\s*|\t+")
LEAD_NOISE = re.compile(
    r"^\s*[\u09e6-\u09ef0-9]+\s*[.)\u0964]?\s*|\s*\(?[\u09e6-\u09ef0-9]{1,2}[.)]\s*")


def clean_cell(c):
    c = LEAD_NOISE.sub("", c or "", count=1)
    c = re.sub(r"[`*_]+", "", c)
    return tidy(c).strip(";:,")


def split_table(text):
    """Return (header_cells, [row_cells]) for a pipe/tab table, else (None, []).

    Leading lines without a delimiter (e.g. the "[ধারা ২(৮) ও ৬(১)]" note that
    precedes a schedule) are skipped rather than treated as end-of-table.

    Gazette tables often label a serial column ("ক্রমিক নং") that the body
    instead glues onto the first real cell ("১। কৃষি অঞ্চল | AZ | ..."), so the
    body ends up one column narrower than the header.  When that is the case the
    body is padded to keep the header's column indices valid.
    """
    lines = []
    for ln in (text or "").splitlines():
        raw = ln.rstrip()
        if not raw.strip() or not re.search(r"\||\t", raw):
            if lines:
                break
            continue
        cells = [clean_cell(c) for c in CELL_SPLIT.split(raw)]
        if sum(1 for c in cells if c) < 3:
            if lines:
                break
            continue
        lines.append(cells)
    if len(lines) < 3:
        return None, []

    header, data = lines[0], lines[1:]
    widths = {}
    for r in data:
        widths[len(r)] = widths.get(len(r), 0) + 1
    if not widths:
        return None, []
    body_w = max(widths.items(), key=lambda kv: kv[1])[0]
    head_w = len(header)

    if body_w == head_w:
        keep = [r for r in data if len(r) == head_w]
    elif body_w == head_w - 1:
        # serial number is glued onto the first real column
        keep = [[""] + r for r in data if len(r) == body_w]
    else:
        keep = [r for r in data if len(r) == head_w]
    if len(keep) < 2:
        return None, []
    return header, keep


def _col(header, *words):
    """Index of the first header cell whose text contains any of `words`."""
    for i, h in enumerate(header):
        hl = re.sub(r"[^ঀ-৿]", "", h)
        for w in words:
            if w in hl:
                return i
    return -1


def table_qa(header, rows, scope, label, cap=200):
    """Q&A per table row, driven by recognised column roles.

    Deduplication is by *question*, not by answer: several distinct questions
    legitimately share one answer (e.g. "কারাদণ্ড কত?" and "অর্থদণ্ড কত?" both
    answer with the punishment cell), and a column whose value is constant
    across every row is better served by one aggregate question.
    """
    if not header or not rows:
        return []
    scope = tidy(scope) or "এই আইন"
    label = tidy(label) or "তফসিল"
    out, seen_q = [], set()

    i_name = _col(header, "অপরাধ", "বিষয়ের নাম", "জোনের নাম", "নাম", "বিষয়", "title", "name")
    if i_name < 0:
        i_name = _col(header, "বর্ণনা", "বিবরণ", "বিষয়বস্তু", "description")
    if i_name < 0:
        i_name = 0
    i_code = _col(header, "কোড", "code", "সংকেত", "পরিচয়")
    i_desc = _col(header, "বর্ণনা", "বিবরণী", "description", "ব্যাখ্যা")
    if i_desc == i_name:
        i_desc = -1
    i_amol = _col(header, "আমলযোগ্যতা", "আমল")
    i_jam = _col(header, "জামিনযোগ্যতা", "জামিন")
    i_apol = _col(header, "আপোষযোগ্যতা", "আপোষ")
    i_dan = _col(header, "আরোপণীয় দণ্ড", "দণ্ড", "শাস্তি", "punishment")

    if all(x < 0 for x in (i_code, i_desc, i_amol, i_jam, i_dan)):
        return []

    def push(q, a):
        a = tidy(a)
        if len(a) < 4 or len(q) < 10:
            return
        k = squash(q)
        if k in seen_q:
            return
        seen_q.add(k)
        out.append((q, a))

    def name_of(r):
        if len(r) <= i_name or not r[i_name]:
            return None
        nm = r[i_name]
        return None if len(nm) < 3 or nm in header else nm

    # --- classification columns: aggregate when constant, else per row ---
    for idx, tag, agg_q in (
        (i_amol, "আমলযোগ্যতা", f"{scope} {label} অনুযায়ী কোনগুলো আমলযোগ্য?"),
        (i_jam, "জামিনযোগ্যতা", f"{scope} {label} অনুযায়ী কোনগুলো জামিনযোগ্য?"),
        (i_apol, "আপোষযোগ্যতা", f"{scope} {label} অনুযায়ী কোনগুলো আপোষযোগ্য?"),
    ):
        if idx < 0:
            continue
        pairs = [(name_of(r), r[idx]) for r in rows
                 if name_of(r) and len(r) > idx and r[idx]]
        if not pairs:
            continue
        vals = {v for _, v in pairs}
        if len(vals) == 1:
            only = pairs[0][1]
            push(agg_q, f"{label}-এর সব ক্ষেত্রে এই মানটি প্রযোজ্য: {only}। "
                        f"সংশ্লিষ্ট {bn_num(len(pairs))}টি বিষয়: "
                        + "; ".join(n for n, _ in pairs)[:700])
        else:
            for nm, v in pairs:
                push(f"{scope} {label}-এ \"{nm}\" এর {tag}তা কী?", v)

    for r in rows:
        name = name_of(r)
        if not name:
            continue

        if i_code >= 0 and len(r) > i_code and r[i_code]:
            code = r[i_code]
            push(f"{scope} {label}-এ \"{code}\" কোডটি কোন জোন বা বিষয়ের?", name)
            push(f"{scope} {label}-এ \"{name}\" এর কোড কী?", code)

        if i_desc >= 0 and len(r) > i_desc and len(r[i_desc]) > 14:
            push(f"{scope} {label}-এ \"{name}\" বিষয়টির বর্ণনা কী?", r[i_desc])

        if i_dan >= 0 and len(r) > i_dan and len(r[i_dan]) > 8:
            d = r[i_dan]
            push(f"{scope} অনুযায়ী \"{name}\" এর শাস্তি বা দণ্ড কত?", d)
            mp = PUNISH_RE.search(d)
            if mp and _digits_ok(mp.group(1)):
                val = value_label(mp.group(1), mp.group(2), punish_unit(mp))
                push(f"{scope} অনুযায়ী \"{name}\" এর জন্য কারাদণ্ড কত? ({val})", d)
            ma = AMMONY_RE.search(d)
            if ma and _digits_ok(ma.group(2)):
                val = value_label(ma.group(2), ma.group(3), ma.group(4))
                push(f"{scope} অনুযায়ী \"{name}\" এর জন্য অর্থদণ্ড কত? ({val})", d)

        if len(out) >= cap:
            break

    if len(rows) >= 2:
        names = [name_of(r) for r in rows if name_of(r)]
        push(f"{scope} {label}-এ মোট কয়টি সারি বা বিষয় চিহ্নিত করা হয়েছে?",
             f"{scope} এর {label}-এ মোট {bn_num(len(rows))}টি সারি চিহ্নিত করা হয়েছে। "
             + "সারিগুলো: " + " | ".join(names)[:700])
    return out[:cap]
