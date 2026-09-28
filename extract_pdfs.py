import os, sys, io, json, re, fitz
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PDF_DIR = 'pdfs'
OUT_DIR = 'pdf_text'
os.makedirs(OUT_DIR, exist_ok=True)

def strip_pdf_header(text):
    # remove bdlaws header lines and numbering artifacts
    lines = text.split('\n')
    keep = []
    for ln in lines:
        s = ln.strip()
        if re.match(r'^bdlaws\.minlaw\.gov\.bd', s): continue
        if re.match(r'^\d+/\d+$', s): continue
        if re.match(r'^\d{2}/\d{2}/\d{4}$', s): continue
        keep.append(ln)
    return '\n'.join(keep)

def extract(path):
    doc = fitz.open(path)
    parts = []
    for i in range(doc.page_count):
        parts.append(doc[i].get_text())
    doc.close()
    return strip_pdf_header('\n'.join(parts))

def text_quality(s):
    ln = len(s)
    if not ln: return 'empty', 0
    bn = sum(1 for c in s if '\u0980' <= c <= '\u09ff')
    # high bytes via utf-8 encode excluding bengali 3-byte leads
    b = s.encode('utf-8', errors='replace')
    hi = sum(1 for x in b if x >= 0x80 and not (0xE0 <= x <= 0xEF))
    ascii_c = sum(1 for c in s if 32 <= ord(c) < 127)
    if bn > 400 and bn > ln*0.2:   return 'unicode-bengali', bn
    if ascii_c > ln*0.7 and ln>500: return 'english', 0
    if hi > 300:                     return 'legacy', hi
    if bn > 100:                     return 'bengali-mixed', bn
    return 'mixed', max(bn,hi)

for f in sorted(os.listdir(PDF_DIR)):
    if not f.lower().endswith('.pdf'): continue
    p = os.path.join(PDF_DIR, f)
    try:
        text = extract(p)
    except Exception as e:
        print(f"ERR {f}: {e}")
        continue
    cls, n = text_quality(text)
    # keep usable ones
    outname = f.rstrip('.pdf') + '.txt'
    if cls in ('unicode-bengali','english') and len(text)>500:
        with open(os.path.join(OUT_DIR, outname), 'w', encoding='utf-8') as fh:
            fh.write(text)
        print(f"KEEP [{cls:>16}] {len(text):>8} chars  {outname[:48]}")
    else:
        print(f"SKIP [{cls:>16}] {len(text):>8} chars  {f[:48]}")