"""Q&A extraction from text-layered PDFs in the `pdfs/` folder.

The SQL dump stores most circulars/policies/manuals only as external PDF paths,
so their legal text is not in the DB. This module reads the extracted plain-text
versions (produced by extract_pdfs.py into pdf_text/) for the curated documents
that have a clean text layer (genuine English acts + good Unicode-Bengali docs),
and generates DB-style Q&A entries: per-document intro, clause-level questions,
a summary, definitional questions, fact questions, plus a `more` field carrying
the full document text for the follow-up feature.
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_DIR = os.path.join(HERE, "pdf_text")

# ---- Curated include list (quality text; legacy-encoded & scanned PDFs excluded) ----
ENGLISH_DOCS = [
    "An_Ordinance_to_repeal_the_Vested_and_Non-Resident_Property_Administration_Act_1974.txt",
    "CHT-Regulation-1900.txt",
    "THE_BANGLADESH_LAND_HOLDING_LIMITATION_ORDER_1972.txt",
    "THE_BENGAL_ALLUVION_AND_DILUVION_REGULATION_1825.txt",
    "The_Acquisition_of_Waste_Land_Act_1950_East_Bengal_Act.txt",
    "The_Alienation_of_Land_Distressed_Circumstances_Restoration_Ordinance_1976.txt",
    "The_Alluvial_Lands_Act_1920.txt",
    "The_Alluvion_Amendment_Act_1868.txt",
    "The_Bengal_Records_Manual_1943.txt",
    "The_Court-fees_Act_1870.txt",
    "The_Foreign_Voluntary_Organisations_Acquisition_o.txt",
    "The_Hindu_Inheritance_Removal_of_Disabilities_Act_1928.txt",
    "The_Hindu_Law_of_Inheritance_Amendment_Act_1929.txt",
    "The_Hindu_Womens_Rights_to_Property_Act_1937.txt",
    "The_Hindu_Womens_Rights_to_Property_Extension_to_Agricultural_Land_Act_1943_Assam_Act.txt",
    "The_Land_Development__Tax_Ordinance_1976.txt",
    "The_Limitation_Act_1908.txt",
    "The_Mussalman_Wakf_Validating_Act_1930.txt",
    "The_Non-Agricultural_Tenancy_Act_1949_East_Bengal_Act.txt",
    "The_Prevention_of_Transfer_of_Property_and_Removal_of_Documents_and_Records_Act_1952_.txt",
    "The_Public_Demands_Recovery_Act_1913_Bengal_Act.txt",
    "The_State_Acquisition_Ad-interim_Payment_Act_1957_East_Pakistan_Act.txt",
    "The_State_Acquisition_Bonds_Act_1957_East_Pakistan_Act.txt",
    "ThebBangladeshnGovernment_Hats_and_Bazars_Management_Repeal_Ordinance_1975.txt",
    "the_land_reforms_ordinance_1984.txt",
]

BENGALI_DOCS = [
    "All_circular_-1-13.txt",
    "All_circular_-14-26.txt",
    "Land_Administrtion_Manual-3.txt",
    "Land_Khatian_Chittagong_Hill_Tracts_Ordinance_1984.txt",
    "অসথবর_সমপতত_হকমদখল_আইন_১৯৮৮.txt",
    "ই-নমজর_সসটম_নমজর_আবদন_নষপতত_করর_বষয়_নরদশন.txt",
    "কষ_খসজম_বযবসথপন_ও_বনদবসত_নতমল_সরবশষ_সশধনসহ.txt",
    "জতয়_নদ_রকষ_কমশন_আইন২০১৩.txt",
    "জল_ভমসব_কনদর_বযবসথপন_নরদশক_২০২৬.txt",
    "ঢক_এলভটড_একসলপরসওয়_পরকলপ_ভম_অধগরহন_আইন২০১১.txt",
    "পদম_বহমখ_সত_পরকলপ_ভম_অধগরহণ_আইন২০০৯.txt",
    "বলমহল_ও_মট_বযবসথপন_আইন২০১০.txt",
    "ভম_আপল_বরড_আইন_১৯৮৯.txt",
    "ভম_সবয়_সহয়ত_পরদন_ও_বযবসথপন_নরদশক.txt",
    "ভম_সসকর_বরড_আইন_১৯৮৯.txt",
    "ভমসবয়_অভযগ_বযবসথপন_নরদশক_২০২৬.txt",
    "ভমসবয়_সইবর_নরপতত_ও_তথয_সরকষ_নরদশক_সসকরণ_১.০_২০২৬.txt",
    "মহনগর_বভগয়_শহর_ও_জল_শহরর_পর_এলকসহ_দশর_সকল_পর_এলকর_খলর_মঠ_উনমকত_সথন_উদযন_এব_পরকতক_uws3nYs.txt",
    "যমন_বহমখ_সত_পরকলপ_ভম_অধগরহণ_আইন_১৯৯৫.txt",
    "সব-রজসটর_অফস_হত_দললর_একট_নটশ_একট_কপ_পরপতর_পর_নমজর_করযকরম_সমপন_r.txt",
]

KEEP = ENGLISH_DOCS + BENGALI_DOCS

# Page/header artifacts to drop
ARTIFACT_RE = re.compile(
    r"^\s*(পাতা\s*\d+\s*/\s*\d+|\d+\s*/\s*\d+\s*|bdlaws\.minlaw\.gov\.bd"
    r"|[0-9]{2}/[0-9]{2}/[0-9]{4}|Laws of Bangladesh)\s*$")

TITLE_OVERRIDES = {
    "ভম_আপল_বরড_আইন_১৯৮৯.txt": "ভূমি আপীল বোর্ড আইন, ১৯৮৯",
    "ভম_সসকর_বরড_আইন_১৯৮৯.txt": "ভূমি সংস্কার বোর্ড আইন, ১৯৮৯",
    "বলমহল_ও_মট_বযবসথপন_আইন২০১০.txt": "বালুমহাল ও মাটি ব্যবস্থাপনা আইন, ২০১০",
    "জল_ভমসব_কনদর_বযবসথপন_নরদশক_২০২৬.txt": "জেলা ভূমিসেবা কেন্দ্র ব্যবস্থাপনা নির্দেশিকা, ২০২৬",
    "ভমসবয়_সইবর_নরপতত_ও_তথয_সরকষ_নরদশক_সসকরণ_১.০_২০২৬.txt":
        "ভূমিসেবায় সাইবার নিরাপত্তা ও তথ্য সুরক্ষা নির্দেশিকা (সংস্করণ ১.০), ২০২৬",
    "কষ_খসজম_বযবসথপন_ও_বনদবসত_নতমল_সরবশষ_সশধনসহ.txt":
        "কৃষি খাসজমি ব্যবস্থাপনা ও বন্দোবস্ত নীতিমালা (সর্বশেষ সংশোধনসহ)",
    "ভমসবয়_অভযগ_বযবসথপন_নরদশক_২০২৬.txt": "ভূমিসেবায় অভিযোগ ব্যবস্থাপনা নির্দেশিকা, ২০২৬",
    "ভম_সবয়_সহয়ত_পরদন_ও_বযবসথপন_নরদশক.txt": "ভূমিসেবা সহায়তা প্রদান ও ব্যবস্থাপনা নির্দেশিকা, ২০২৫",
    "অসথবর_সমপতত_হকমদখল_আইন_১৯৮৮.txt": "অস্থাবর সম্পত্তি হুকুমদখল আইন, ১৯৮৮",
    "জতয়_নদ_রকষ_কমশন_আইন২০১৩.txt": "জাতীয় নদী রক্ষা কমিশন আইন, ২০১৩",
    "যমন_বহমখ_সত_পরকলপ_ভম_অধগরহণ_আইন_১৯৯৫.txt": "যমুনা বহুমুখী সেতু প্রকল্প (ভূমি অধিগ্রহণ) আইন, ১৯৯৫",
    "ঢক_এলভটড_একসলপরসওয়_পরকলপ_ভম_অধগরহন_আইন২০১১.txt":
        "ঢাকা এলিভেটেড এক্সপ্রেসওয়ে প্রকল্প (ভূমি অধিগ্রহণ) আইন, ২০১১",
    "পদম_বহমখ_সত_পরকলপ_ভম_অধগরহণ_আইন২০০৯.txt": "পদ্মা বহুমুখী সেতু প্রকল্প (ভূমি অধিগ্রহণ) আইন, ২০০৯",
    "ই-নমজর_সসটম_নমজর_আবদন_নষপতত_করর_বষয়_নরদশন.txt":
        "ই-নামজারি সিস্টেমে নামজারি আবেদন নিষ্পত্তি করার বিষয়ে নির্দেশনা",
    "সব-রজসটর_অফস_হত_দললর_একট_নটশ_একট_কপ_পরপতর_পর_নমজর_করযকরম_সমপন_r.txt":
        "সাব-রেজিস্ট্রি অফিস হতে দলিলের একটি নোটিশ ও একটি কপি প্রাপ্তির পর নামজারি কার্যক্রম",
    "মহনগর_বভগয়_শহর_ও_জল_শহরর_পর_এলকসহ_দশর_সকল_পর_এলকর_খলর_মঠ_উনমকত_সথন_উদযন_এব_পরকতক_uws3nYs.txt":
        "অনাবাসিক ভবনের পৌর এলাকার খেলার মাঠ, উন্মুক্ত স্থান, উদ্যান ও পার্ক রক্ষণাবেক্ষণ",
}

TT_BN_RE = re.compile(r"[\u0980-\u09ff]")

# clause markers: bengali "ধারা ৫" / "৫.৫" ; english "Section 5." / "5."
# Bengali section terminator includes the danda "(রা" U+09F7 and halant danda U+09E4
BN_CLAUSE_RE = re.compile(
    r"(?:^|\n)\s*(?:ধারা\s*)?([০-৯]{1,3})(?:[।\.১৷])\s+(?=\S)")
EN_CLAUSE_RE = re.compile(
    r"(?:^|\n)\s*(?:Section\s+)?([0-9]{1,3}(?:\.[0-9]{1,3})?)\s*\.\s+(?=[A-Z])")


def _load_text(fname):
    p = os.path.join(TEXT_DIR, fname)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _normalize(text):
    lines = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if ARTIFACT_RE.match(s):
            continue
        lines.append(s)
    return "\n".join(lines)


def _title(fname):
    return TITLE_OVERRIDES.get(fname, fname[:-4].replace("_", " "))


def _bn2en(s):
    m = {"০": "0", "১": "1", "২": "2", "৩": "3", "৪": "4",
         "৫": "5", "৬": "6", "৭": "7", "৮": "8", "৯": "9"}
    return "".join(m.get(c, c) for c in s)


def extract_pdf_entries():
    """Return a list of {q, a, more, tpl} items derived from the curated PDF corpus."""
    import build_db as b
    out = []
    taken = set()

    def add(q, a_raw, title=None, more_raw=None):
        a = b.strip_html(a_raw)
        if len(a) > b.MAX_ANS:
            a = a[:b.MAX_ANS].rstrip() + "…"
        if "????" in q or "????" in a:
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

    docs = []
    for fname in KEEP:
        text = _load_text(fname)
        if not text or len(text.strip()) < 50:
            continue
        docs.append((fname, _title(fname), _normalize(text)))

    # catalog overview question (enumerate all 45 accessible PDFs)
    overview_lines = [d[1] for d in docs]
    overview = ("বহিঃস্থ নথি (PDF) থেকে সংগৃহীত মোট {}টি দলিল আছে।\n\n"
                .format(len(docs)) + "\n".join(f"• {t}" for t in overview_lines))
    add_many(["বহিঃস্থ নথি", "বহিঃস্থ নথিগুলো কি কি?", "ভূমি আইনের PDF নথি সমূহ",
              "PDF নথি সমূহ"], overview)

    for fname, title, text in docs:
        is_bn = TT_BN_RE.search(title) or TT_BN_RE.search(text[:300])
        intro = f"{title}\n(সংগৃহীত: বহিঃস্থ নথি PDF থেকে)"
        add_many([title, f"{title} কি?", f"{title} সম্পর্কে জানতে চাই"], intro, title)

        # clause-level splitting
        cls_re = BN_CLAUSE_RE if is_bn else EN_CLAUSE_RE
        markers = [(m.start(), m.group(1), m.end()) for m in cls_re.finditer(text)]
        markers = sorted(markers)
        # dedupe overlapping markers (keep first of same start)
        dedup = []
        last = -1
        for st, num, en in markers:
            if st == last:
                continue
            last = st
            dedup.append((st, num, en))
        markers = dedup[:80]

        for i, (st, num, en) in enumerate(markers):
            e2 = markers[i + 1][0] if i + 1 < len(markers) else len(text)
            clause = text[en:e2].strip()
            # filter out TOC heading-only entries (no sentence content)
            if len(clause) < 12:
                continue
            if re.search(r"[\u0980-\u09ff]", clause):
                has_sentence = ("।" in clause) or ("। " in clause)
                if len(clause) < 50 and not has_sentence:
                    continue
            else:
                # English: require a real sentence (terminal period) or a
                # semicolon-heavy body (legal clauses use them)
                if not re.search(r"\.\s+[A-Z]", clause) \
                        and not re.search(r";", clause):
                    continue
            clause = re.sub(r"\s+", " ", clause)[:4500]
            numdisp = _bn2en(num) if not is_bn else num
            if is_bn:
                add_many([f"{title} এর {numdisp} অনুচ্ছেদ কি বলে?",
                          f"{title} অনুযায়ী {numdisp} নম্বর অংশ"],
                         clause, title, text)
            else:
                add_many([f"{title} এর Section {numdisp} কি?",
                          f"{title} অনুযায়ী section {numdisp} এ কি বলা হয়েছে?"],
                         clause, title, text)
            # fact questions within the clause
            for fq, fa in b.fact_questions(clause, title, title):
                add(fq, fa, title, clause)

        # summary = first non-empty paragraph
        first_par = ""
        for para in text.split("\n"):
            if len(para.strip()) >= 25 and "সংগৃহীত" not in para:
                first_par = para.strip()
                break
        if first_par:
            first_par = re.sub(r"\s+", " ", first_par)
            if len(first_par) > 600:
                first_par = first_par[:600].rstrip() + "…"
            add(f"{title} এর সারসংক্ষেপ", first_par, title, text)

    return out


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    items = extract_pdf_entries()
    print(f"extract_pdf_entries(): {len(items)} Q&A")
    for it in items[:5]:
        print("  Q:", it["q"][:70])
        print("  A:", it["a"][:90], "…")