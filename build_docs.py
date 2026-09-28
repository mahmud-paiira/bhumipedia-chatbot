import io
import os
import re
import sys
import json
import urllib.parse

import requests
from pypdf import PdfReader

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import logging
logging.getLogger("pypdf").setLevel(logging.ERROR)

import unicodedata

ALLOWED_PUNCT = set(".,;:!?()[]{}'\"-\u2013\u2014/\u0964\u0981\u09CD\u0982%+=*&#@_"
                    "\u2026\u2018\u2019\u201c\u201d\u2022\u00d7\u00f0\u09e4\u09f6"
                    "\u2190\u2191\u2192\u2193\u09f3\u00a9\u00ae\u09e5")


def _ok_char(c):
    if c.isspace():
        return True
    return unicodedata.category(c)[0] in "LMN" or c in ALLOWED_PUNCT

BASE = "https://bhumipedia.land.gov.bd/uploads/PDF/Act/"
HERE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(HERE, "pdfs")
DOC_BUDGET = 2_500_000
CHUNK_SIZE = 700
MAX_FILE_MB = 26

SKIP_PATTERNS = [
    "dummy", "page0", "testschedule", "application-", "asdfg",
    "situational_alert", "ecih-brochure", "astm_", "letter_to_dream",
    "ebook_tor", "notesheet", "test_book", "system_generated",
    "1772597141313", "5a73e0a7",
]

JUNK_TITLES = re.compile(
    r"(cyber|threat|brochure|soil\s*clas|test\b|schedule)", re.I
)


def listing():
    r = requests.get(BASE, timeout=60)
    r.raise_for_status()
    html = r.text
    items = []
    seen = set()
    for m in re.finditer(r'href="([^"]+?\.pdf)"[^>]*>(.*?)</a>', html, re.I | re.S):
        href = m.group(1)
        disp = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if href in seen:
            continue
        seen.add(href)
        items.append({"href": urllib.parse.unquote(href), "raw": href,
                      "name": urllib.parse.unquote(disp), "size": None})
    return items


def sizes_for(items):
    out = []
    for it in items:
        name = it["href"]
        low = name.lower()
        if any(p in low for p in SKIP_PATTERNS):
            continue
        if JUNK_TITLES.search(name):
            continue
        out.append(it)
    return out


def head_sizes(items):
    s = requests.Session()
    sized = []
    for it in items:
        try:
            h = s.head(BASE + urllib.parse.quote(it["raw"]), timeout=30,
                       allow_redirects=True)
            cl = int(h.headers.get("Content-Length", 0) or 0)
        except Exception:
            cl = 0
        it["size"] = cl
        sized.append(it)
    return sized


def dedupe(items):
    best = {}
    for it in items:
        key = it["size"]
        if not key:
            best[it["href"]] = it
            continue
        cur = best.get(key)
        def badness(x):
            n = x["href"]
            rnd = len(re.findall(r"_[A-Za-z0-9]{7}(?:\.pdf)?$", n))
            return (rnd * 1000 + len(n), n)
        if cur is None or badness(it) < badness(cur):
            best[key] = it
    return sorted(best.values(), key=lambda x: x["href"])


def download(items):
    os.makedirs(PDF_DIR, exist_ok=True)
    s = requests.Session()
    kept = []
    for i, it in enumerate(items, 1):
        mb = it["size"] / 1e6
        if mb > MAX_FILE_MB:
            print(f"[{i}/{len(items)}] SKIP(too big {mb:.0f}MB) {it['href']}")
            continue
        safe = re.sub(r"[^\w.\-\u0980-\u09FF]+", "_", it["href"])
        path = os.path.join(PDF_DIR, safe)
        it["_path"] = path
        if os.path.exists(path) and os.path.getsize(path) == it["size"]:
            print(f"[{i}/{len(items)}] have  {safe}")
            kept.append(it)
            continue
        try:
            resp = s.get(BASE + it["raw"], timeout=180)
            resp.raise_for_status()
            with open(path, "wb") as f:
                f.write(resp.content)
            print(f"[{i}/{len(items)}] got  ({mb:.1f}MB) {safe}")
            kept.append(it)
        except Exception as e:
            print(f"[{i}/{len(items)}] FAIL {it['href']}: {e}")
    return kept


def clean(text):
    text = text.replace("\u0000", " ")
    text = re.sub(r"-\n", "", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    return text.strip()


BIJOY_RE = re.compile(
    r"(evsjv|kvmb|mvB|Rvb|AvBb|cÖKvwkZ|msL¨v|KZ…©c|†iwR|wW G|‡K…|m½|g½e)"
)

EN_WORDS_RE = re.compile(
    r"\b(the|of|and|act|land|government|section|order|rules|property)\b", re.I
)
HARSH_RE = re.compile(r"[<>{}\\|~^\$\[\]]")


def text_quality(t):
    n = max(len(t), 1)
    if HARSH_RE.findall(t) and len(HARSH_RE.findall(t)) / n > 0.015:
        return None
    bn = sum(1 for c in t if "\u0980" <= c <= "\u09FF")
    latin = sum(1 for c in t if c.isascii() and c.isalpha())
    weird = sum(1 for c in t if not _ok_char(c))
    if weird / n > 0.05:
        return None
    if bn / n >= 0.18:
        return "bn"
    if latin / n >= 0.55 and len(EN_WORDS_RE.findall(t)) >= max(3, n // 400):
        return "en"
    return None


CONS = "\u0995-\u09B9\u09DC\u09DD\u09DF\u09CE\u09E0\u09E1"
PRE_SIGNS = "\u09BF\u09C7\u09C8\u09CB"  # ি ে ৈ ো


def fix_matras(text):
    bad = len(re.findall(f"[{PRE_SIGNS}](?=[{CONS}])", text))
    good = len(re.findall(f"(?<=[{CONS}])[{PRE_SIGNS}]", text))
    if bad > 20 and bad > good * 0.8:
        pat = f"([{PRE_SIGNS}])([{CONS}](?:\u09cd[{CONS}])*)"
        text = re.sub(pat, r"\2\1", text)
    return text


def sentences(text):
    parts = re.split(r"(?<=[।?!])\s+|\n+|\.{4,}\s*", text)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def chunk_pages(pages_text):
    chunks = []  # (page_no, text, [(start,end), ...] spans of sentences)
    for page_no, txt in pages_text:
        buf, spans, pos = [], [], 0
        for sent in sentences(txt):
            if sum(len(x) for x in buf) + len(sent) >= CHUNK_SIZE and buf:
                chunks.append((page_no, " ".join(buf), spans))
                buf, spans = [], []
                pos = 0
            spans.append((pos, pos + len(sent)))
            pos += len(sent) + 1
            buf.append(sent)
        if buf:
            chunks.append((page_no, " ".join(buf), spans))
    return chunks


def extract_title(first_text, fallback):
    for line in first_text.split("\n"):
        line = clean(line).strip(" -–—0123456789।,;:")
        if len(line) < 4:
            continue
        q = text_quality(line)
        if not q or BIJOY_RE.search(line):
            continue
        if re.match(r"^(page|www|http|bdlaws)", line, re.I):
            continue
        return line[:90]
    return fallback


def process(kept):
    docs = []
    total_chars = 0
    skipped_scanned, budget_hit = [], False
    for it in kept:
        path = it.get("_path")
        if not path or not os.path.exists(path):
            continue
        title_fallback = re.sub(r"_+", " ", os.path.splitext(it["href"])[0]).strip()
        try:
            reader = PdfReader(path)
            n_pages = len(reader.pages)
        except Exception as e:
            print(f"  ! unreadable: {title_fallback} ({e})")
            continue
        pages_text = []
        chars_here = 0
        for pi in range(n_pages):
            try:
                raw = reader.pages[pi].extract_text() or ""
            except Exception:
                raw = ""
            raw = clean(raw)
            raw = fix_matras(raw)
            if raw:
                pages_text.append((pi + 1, raw))
                chars_here += len(raw)
        if chars_here < 1500:
            skipped_scanned.append(title_fallback)
            print(f"  - no usable text (scanned/legacy): {title_fallback}")
            continue
        first_page = next((t for _, t in pages_text), "")
        title = None
        chunks_here = []
        for page_no, chunk, spans in chunk_pages(pages_text):
            if len(chunk) < 100:
                continue
            q = text_quality(chunk)
            if not q or BIJOY_RE.search(chunk):
                continue
            if title is None:
                title = extract_title(first_page, title_fallback)
            if total_chars + len(chunk) > DOC_BUDGET:
                budget_hit = True
                break
            docs.append({
                "t": title, "p": page_no, "x": chunk,
                "f": BASE + it["raw"],
                "sent": [[a, b] for a, b in spans],
            })
            total_chars += len(chunk)
            chunks_here.append(chunk)
        if not chunks_here:
            skipped_scanned.append(title_fallback)
            print(f"  - no usable text (scanned/legacy): {title_fallback}")
            continue
        if budget_hit:
            print("  ! doc text budget reached, stopping early")
            break
        print(f"  ok [{n_pages:>3}p {chars_here//1000:>5}k] {title[:70]}")
    return docs, skipped_scanned


def main():
    print("Fetching listing ...")
    items = listing()
    print(f"  {len(items)} pdf links found")
    items = sizes_for(items)
    print(f"  {len(items)} after junk filter")
    items = head_sizes(items)
    items = dedupe(items)
    print(f"  {len(items)} after size-dedupe; "
          f"{sum(i['size'] for i in items)/1e6:.0f}MB to download\n")

    kept = download(items)
    print(f"\nDownloaded/present: {len(kept)} files. Extracting ...\n")
    docs, scanned = process(kept)

    out = ["const DOC_BASE = %s;" % json.dumps(BASE),
           "const DOCS = ",
           json.dumps(docs, ensure_ascii=False), ";"]
    with open(os.path.join(HERE, "docs.js"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    report = {
        "files_kept": len(kept),
        "chunks": len(docs),
        "text_chars": sum(len(d["x"]) for d in docs),
        "scanned_or_empty": scanned,
    }
    with open(os.path.join(HERE, "docs_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nOK: {len(docs)} chunks, {report['text_chars']//1000}k chars -> docs.js")
    if scanned:
        print(f"Skipped (no text layer): {len(scanned)}")


if __name__ == "__main__":
    main()
