# ভূমি বন্ধু — Bhumipedia Chatbot

A Bengali (and Assamese) question-answering chatbot for Bangladesh land-services
law, built on the iLKMS platform's statutes and the
[Bhumipedia](https://bhumipedia.land.gov.bd) land portal.

**There is no LLM in this project.** Every answer is a real entry from a bundled
corpus, matched with a hand-written lexical scorer and returned verbatim. That
means replies are exact and cannot hallucinate — and, as the trade-off, the bot
can only answer what is in the dataset.

- **57,678** Q&A pairs in `data.js`
- Plus PDF passage chunks in `docs.js` for long-form document search
- Runs **fully offline** from static files; an optional live API serves the same
  answers from PostgreSQL

---

## How it works

```
                 ┌──────────────────────────┐
 user query ───▶ │  norm() → tokenize()     │
                 │  → scoreEntry()           │──▶ verbatim Q&A + passage
                 └───────────┬──────────────┘
                             │
        ┌────────────────────┴────────────────────┐
        │                                         │
  data.js (offline)                    PostgreSQL (live)
  57,678 Q&A                           server.py → scorer.py
```

The client is plain static JavaScript — no bundler, no framework, no build step.
`index.html` loads `app.js`, `data.js` and `docs.js` directly, and answers from
`data.js` unless `window.__BHUMI_API__` is set (see
[Optional: live API](#optional-live-api)).

Scoring is weighted token overlap: longer words weigh more, prefix matches get
partial credit, and an exact normalized match returns score `1000`.

---

## Quick start

The app is static. Serve the directory with any web server and open it:

```bash
python -m http.server 8000
# → http://localhost:8000
```

Opening `index.html` directly from the filesystem also works, but a server is
recommended (browsers restrict `fetch` to `file://`).

### Optional: live API

The app is **offline-first**: `index.html` ships `window.__BHUMI_API__ = ""`, so
by default it never makes a network request and answers entirely from `data.js`.
Live mode is opt-in.

```bash
pip install -r requirements.txt
cp .env.example .env      # then set DATABASE_URL
python server.py          # → http://127.0.0.1:8790
```

Then point the client at it in `index.html` (before `app.js` loads):

```html
<script>window.__BHUMI_API__ = "http://127.0.0.1:8790";</script>
```

If the API is empty, unreachable, slow, or returns nothing usable, `app.js`
falls back to the bundled dataset (4 s timeout), so the chatbot keeps working.

Server configuration:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://localhost/iLKMS` | PostgreSQL DSN (URL or keyword string) |
| `BHUMI_HOST` | `127.0.0.1` | Bind address |
| `BHUMI_PORT` | `8790` | Bind port |

Endpoints:

| Route | Returns |
| --- | --- |
| `GET /api/health` | `{"ok": bool, "rows": {...}}` |
| `GET /api/search?q=...&lang=bn` | Same response shape as `findAnswer()` |
| `GET /api/stats` | Dataset size and source row counts |

---

## Rebuilding the dataset

> **Note:** the generated datasets (`data.js`, `docs.js`) are committed, so you do
> **not** need to rebuild to run the app. The source exports are *not* committed
> (see [Data sources](#data-sources) and `.gitignore`), so a rebuild needs them
> re-supplied.

```bash
python build_data.py      # → data.js  (57,678 entries)
python build_docs.py      # → docs.js  + docs_report.json (downloads act PDFs)
```

`build_data.py` reads the SQL dump named by `build_db.SQL_PATH`
(`d71_ilkms_5000_dump_2026.08.23.sql`) and chains the PDF and Bhumipedia
sources. To build from a differently named dump, call the functions directly:

```python
from build_db import load_tables_from_sql, extract_db
items = extract_db(load_tables_from_sql("path/to/your_dump.sql"))
```

### Probes (no output files)

```bash
python build_db.py             # extract_db(): candidate count + samples
python pdf_source.py           # PDF-derived Q&A
python bhumipedia_source.py    # portal-derived Q&A
python bhumipedia_source.py --refresh   # bypass the HTTP cache
```

### Pipeline stages

| Stage | Module | Output |
| --- | --- | --- |
| SQL dump → tables | `build_db.load_tables_from_sql()` | `{table: {cols, rows}}` |
| SQL → Q&A | `build_db.extract_db()` | acts, sections, subsections, schedules, blogs |
| Act PDFs → Q&A | `pdf_source.extract_pdf_entries()` | section-level Q&A |
| Act PDFs → passages | `build_docs.py` | `docs.js` chunked text |
| Portal REST → Q&A | `bhumipedia_source.extract_bhumipedia_entries()` | acts, sections, subsections, schedules |
| Live PostgreSQL → Q&A | `db_source.load_tables_from_db()` | identical structure to the SQL path |
| Clean + dedup | `build_data.py` | `data.js` |

`db_source.py` reads `DATABASE_URL` (via `python-dotenv`) and applies the same
`approved = TRUE` export scope as the SQL snapshot, so the live path is designed
to match the static build.

---

## Live related-question suggestions

While the user types, tappable chips appear above the input box with the
questions closest to the partial text in `data.js`.

- Ranked by the **closest dataset entries**, reusing `scoreEntry()`
- The top match is skipped — that one becomes the answer, so the chips are
  genuine alternatives
- Inverted token index, built during browser **idle time** so page load is
  unaffected; ~**5 ms per keystroke**
- Probes the **most selective** word first, so a broad word like `ধারা` (25k
  matches) never swamps a specific one
- A stopword list drops low-signal words (`কি`, `আইন`, `the`, `of`)
- Near-duplicate enumerations are collapsed, so five chips never all read
  `ভূমি জোনিং (১)`, `(২)`, `(৩)`, `(৪)`, `(৫)`
- Bengali/Assamese **IME composition is guarded** — suggestions wait for
  `compositionend` so nothing is guessed mid-composition
- Debounced 180 ms

Typing `ধারা` on its own shows nothing, because it matches 25,836 questions and
narrows nothing down; suggestions appear once a sharper word is present.

---

## Tests

```bash
node test.js          # 35 assertions — dataset=57678
node test_samples.js  # strict expected-answer samples
```

Both suites must report `0 failed`. `test.js` also asserts a latency budget
(warm `liveSuggest` under 15 ms/call) and that no duplicate stems appear in a
near-duplicate cluster.

Python/JS scorer parity (`scorer.py` vs `app.js`) is verified by comparing both
over the real dataset.

---

## Repository layout

```
app.js                  frontend: scorer, related-question suggestions, chat UI
index.html              static shell (loads app.js, data.js, docs.js)
data.js                 57,678 Q&A  (generated)
docs.js                 PDF passage chunks  (generated)

build_db.py             SQL parsing, cleaning, dedup, Q&A generation
build_data.py           writes data.js
build_docs.py           downloads act PDFs → docs.js
pdf_source.py           PDF-derived Q&A
bhumipedia_source.py    Bhumipedia REST loader + Q&A generator (cached)
db_source.py            live PostgreSQL loader
extract_pdfs.py         local PDF text extraction (PyMuPDF, reads `pdfs/`)
scorer.py               Python scoring, shared with server.py
server.py               live API server

test.js                 core regression suite
test_samples.js         expected-answer samples
requirements.txt        Python dependencies
deployment-guide.html   deployment walkthrough
api-integration-guide.html  API contract
```

---

## Data sources

| Source | What is used |
| --- | --- |
| iLKMS PostgreSQL | Acts, sections, subsections, schedules, subschedules, blogs |
| Bhumipedia REST API | Acts, sections, subsections, schedules, subschedules, ebooks, blogs, category |
| Bhumipedia act PDFs | Section text and long-form passages |

Not committed (regenerate or re-supply as needed): `*.sql`, `*.csv`,
`question_bank.md`, `bhumipedia_cache/`, `pdf_text/`, `pdfs/`. Secrets live in
`.env`, which is gitignored — see `.env.example`.

### Current coverage gaps

- `blogs`, `subschedules` and `category` are cached but not yet emitted as Q&A
- Child records are ordered by API `id`, which may differ from statutory order
- A small number of pre-existing SQL-sourced rows are low quality
  (e.g. `Proma Test Aain 2026 june`)
- `server.build_dataset()` parity against a live database is not yet verified
  (requires DB credentials)

---

## License

No license has been declared yet. Add one before publishing.
