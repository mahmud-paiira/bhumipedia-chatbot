"""Shared Q&A clean/dedup pipeline.

Both data.js (via build_data.py) and the public API (via server.py) must derive
the dataset the same way, so the chatbot and /api/v1/qna/ can never disagree.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
CURATED_PATH = os.path.join(HERE, "curated_labels.txt")

_WS = re.compile(r"[ \t\u00a0]+")
_NONWORD = re.compile(r"[^\w\u0980-\u09FF]+")
_SPACES = re.compile(r"\s+")

# The source data spells two Bengali letters with deprecated codepoints that are
# visually identical to the canonical spelling but are different code points:
# U+09DF (YYA) for the canonical YA+NUKTA, and U+09DD (ZHA) for ZZA. They
# appear in a quarter of the corpus - including its most common word,
# "রাষ্ট্ৰীয়" (4481 questions) - while hand-typed queries use the canonical
# form, so those rows could not be matched at all. Canonicalising on both sides
# fixes retrieval, dedup grouping and classification in one move.
_LEGACY = {
    "\u09df": "\u09af\u09bc",  # YYA  -> YA + NUKTA
    "\u09dd": "\u09dc",        # ZHA  -> ZZA
}
_LEGACY_RE = re.compile("[" + "".join(_LEGACY) + "]")


def canonical(s):
    """Map deprecated Bengali codepoints to their canonical spelling."""
    return _LEGACY_RE.sub(lambda m: _LEGACY[m.group(0)], str(s))


def norm(s):
    s = canonical(s).lower()
    s = _NONWORD.sub(" ", s)
    return _SPACES.sub(" ", s).strip()


def clean_text(s):
    return canonical(_WS.sub(" ", str(s))).strip()


# Interrogative scaffolding: present in one phrasing of a question and absent in
# its siblings, carrying no information about WHICH provision is meant. Only
# these are dropped when deriving an identity - section references, numerals,
# act names and section headings are identity and are deliberately kept.
STOP = {
    "আমি", "আপনি", "অনুগ্রহ", "দয়া", "করে", "যদি", "সম্ভব",
    "কি", "বলে", "বলা", "হয়েছে", "বুঝায়", "বোঝায়",
    "সম্পর্কে", "সংক্রান্ত", "জানতে", "চাই", "বিস্তারিত",
    "বলো", "বলুন", "পারবেন", "দরকার", "প্রয়োজন", "হয়ত", "বটে", "উচিত",
    "অনুযায়ী", "মোতাবেক", "অধীনে", "নিয়ে", "এর", "এ", "র", "তার", "তা",
    "কত", "কতটি", "কয়েক", "কোন", "কোনটি", "প্রশ্ন", "উত্তর", "বিষয়ে",
    "ব্যাপারে", "সম্পর্কিত", "অর্থাৎ", "চাইতে",
}


def identity(q):
    """The part of a question that identifies which provision it asks about."""
    return " ".join(w for w in norm(q).split() if w not in STOP)


def load_curated(path=CURATED_PATH):
    """Curated entry-point labels that dedup must never remove.

    These mirror the EXACT tier of test_samples.js. The exact-match tier scores
    1000 only on a literal question match, so a curated label has to exist in
    data.js verbatim. A curated label and an iLKMS re-phrasing of the same
    provision are structurally indistinguishable (e.g. "আইন সমূহ" vs
    "আইন সমূহ কি কি?" share one identity), so the protection is explicit
    rather than inferred.
    """
    if not os.path.exists(path):
        return frozenset()
    with open(path, encoding="utf-8") as f:
        return frozenset(norm(line) for line in f if line.strip())


def clean_rows(items, curated=()):
    """Clean + exact-question dedup, then collapse re-phrasings.

    `items` is the raw {q, a, more?, tpl?} sequence from build_db.extract_db().
    """
    curated = frozenset(curated)
    rows, seen = [], set()
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
        # Taxonomy supplied by the service is authoritative; public_api only
        # falls back to keyword rules for rows the service does not label.
        if it.get("category"):
            ent["c"] = str(it["category"]).strip().lower()
        if it.get("keyword"):
            ent["k"] = clean_text(it["keyword"])
        rows.append(ent)
    return merge_phrasings(rows, curated)


def merge_phrasings(rows, curated=frozenset()):
    """Collapse re-phrasings of the same provision that share one answer.

    The iLKMS dump asks each provision several near-identical ways
    ("... কি", "... সম্পর্কে বিস্তারিত বলো"). Same answer + same provision
    identity means they are the same row, so keep the richest single label.
    Curated labels are never dropped - only unprotected siblings are.
    """
    groups = {}
    for r in rows:
        groups.setdefault((norm(r["a"]), identity(r["q"])), []).append(r)

    merged = []
    for group in groups.values():
        protected = [r for r in group if norm(r["q"]) in curated]
        if len(group) == 1 or len(protected) == len(group):
            merged.extend(group)
            continue
        if protected:
            survivors = protected
        else:
            # Prefer the phrasing that keeps the most distinguishing tokens (it
            # names the Act/section), then the shortest of those.
            survivors = [max(group, key=lambda r: (len(identity(r["q"]).split()),
                                                   -len(norm(r["q"]))))]
        absorbable = [r for r in group if r not in survivors]
        for best in survivors:
            for r in absorbable:
                if r.get("more") and r["more"] not in (best.get("more") or ""):
                    best["more"] = ((best.get("more") or "") + "\n" + r["more"]).strip()
                if r.get("t"):
                    best["t"] = 1
                # a service-labelled sibling lends its taxonomy to the survivor
                for f in ("c", "k"):
                    if r.get(f) and not best.get(f):
                        best[f] = r[f]
        merged.extend(survivors)
    return merged
