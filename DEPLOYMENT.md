# Deployment Guide — ভূমি বন্ধু (Bhumipedia Chatbot)

How this project is deployed, and how to add new questions and answers to the
dataset without breaking the shared pipeline.

## 0. TL;DR

```powershell
# 1. check whether the question is already answered
python add_qna.py --check "নামজারি খতিয়ানের প্রতি কপির ফি কত?"

# 2. add a new question + answer (use files for reliable Bengali on Windows)
python add_qna.py --q-file q.txt --a-file a.txt --category namjari --keyword "নামজারি"

# 3. rebuild the dataset and verify
python build_data.py
node test.js
node test_samples.js

# 4. run it
python -m http.server 8000                 # static mode
python server.py --sql                     # live API mode (no DB needed)
```

The chatbot is **offline-first**: `data.js` answers every query in the browser.
An optional API server (`server.py`) serves the same answers, and the client
falls back to `data.js` whenever the API is unreachable or slow.

---

## 1. What the pieces are

| Piece | Purpose |
|---|---|
| `data.js` / `docs.js` | The searchable corpus the browser loads |
| `app.js` / `index.html` | The chatbot UI + scorer (no framework, no build step) |
| `build_data.py` | Rebuilds `data.js` from all sources |
| `add_qna.py` | The tool for adding new questions and answers |
| `local_qna.json` | The store those additions live in (committed, starts as `[]`) |
| `server.py` | Optional live API on `/api/search`, `/api/stats`, `/api/health` |
| `public_api.py` | Public dataset API mirroring `bhumipedia.land.gov.bd` |

Sources (`build_db`, `api_source`, `bhumipedia_source`, `pdf_source`,
`act_text_source`, `local_qna`) all funnel through `qa_dedup.py`, which
canonicalises Bengali, exact-dedups questions, collapses re-phrasings and
respects `curated_labels.txt`. `data.js` and the API therefore can never
disagree: both run `qa_dedup.clean_rows(extract_db(), curated)`.

---

## 2. Prerequisites

- Python 3.9+ (`pip install -r requirements.txt`)
- Node.js 14+ (only for the test suites)
- The SQL snapshot `d71_ilkms_5000_dump_2026.08.23.sql` (gitignored — needed to
  rebuild; the committed `data.js` works without it)

Optional:

- Internet access for `api_source`/`bhumipedia_source` on first rebuild
  (responses are cached in `api_cache/` and `bhumipedia_cache/`; all gitignored)
- `DATABASE_URL` in `.env` for the live-PostgreSQL server mode (see
  `.env.example`)

---

## 3. Deployment modes

| Mode | Command | When to use |
|---|---|---|
| Static / offline | `python -m http.server 8000` serving the repo directory | Default; zero moving parts, works anywhere |
| Live API, bundled snapshot | `python server.py --sql` | Want `/api/search` without a database |
| Live API, PostgreSQL | `python server.py` | Live refresh from your own iLKMS DB |

Server variables (`server.py` reads these):

| Variable | Default | Purpose |
|---|---|---|
| `BHUMI_HOST` | `127.0.0.1` | Bind address |
| `BHUMI_PORT` | `8790` | Bind port |
| `DATABASE_URL` | `postgresql://localhost/iLKMS` | PostgreSQL DSN (live mode) |

The SQL snapshot used for rebuilds is named by the `SQL_PATH` constant in
`build_db.py` (`d71_ilkms_5000_dump_2026.08.23.sql`); `server.py --sql-path`
points `--sql` mode at a specific file.

To make the client use the API instead of only `data.js`, set in `index.html`
**before** `app.js` loads:

```html
<script>window.__BHUMI_API__ = "http://127.0.0.1:8790";</script>
```

If that address is empty or unreachable, the bot silently uses `data.js`.

For production hardening (systemd, NSSM, nginx reverse proxy, HTTPS, monitoring)
see the full walkthrough in `deployment-guide.html` — this document focuses on
content updates.

---

## 4. Adding new questions and answers

### 4.1 Rule of thumb

**An answer must come from a real source.** The bot's contract is that every
answer is a verbatim entry from the corpus — it does not invent them. Before
you hand-write an answer, prefer the pipeline sources:

1. If the answer already exists on `https://bhumipedia.land.gov.bd` under
   `/api/v1/qna/type1/` or `/type2/`, just refresh and rebuild:
   `python api_source.py --refresh && python build_data.py`.
2. If it belongs in the statutes, add it via the existing statute/act sources.
3. Only when there is genuinely no upstream home (a service notice, a
   correction, expert wording) use `add_qna.py`.

### 4.2 The tool: `add_qna.py`

Stores entries in `local_qna.json`; every build folds them in. Bengali text is
safest passed through UTF-8 files on Windows (shells re-encode command-line
text and can mangle it).

```
usage: add_qna.py [-h] [--q Q] [--q-file Q_FILE] [--a A] [--a-file A_FILE]
                  [--more MORE] [--category CATEGORY] [--keyword KEYWORD]
                  [--tpl] [--note NOTE] [--list] [--check QUESTION]
                  [--remove N] [--dry-run] [--force]
```

| Flag | Meaning |
|---|---|
| `--q`, `--a` | question and answer, inline |
| `--q-file`, `--a-file` | read them from UTF-8 files (recommended) |
| `--more` | an alternative answer for the same question (kept in `more`) |
| `--category` | service category (`khotian`, `namjari`, `khajna`, …). Served **verbatim** by the public API — omit it to let the keyword classifier decide |
| `--keyword` | short label; likewise served verbatim |
| `--tpl` | mark a statutory template answer |
| `--list` | show stored entries |
| `--check QUESTION` | does the dataset already answer this? what wins a query now? |
| `--remove N` | delete entry #N |
| `--dry-run` | validate and show the entry without writing |
| `--force` | add even though the current dataset already answers the question |

### 4.3 The workflow

```powershell
# 1) Are we recreating an answer that already exists?
python add_qna.py --check "জমির নিয়মিত সনদ কি?"
#    -> "no existing entry with that exact question" + current query behaviour

# 2) Add from files (avoids shell encoding issues)
echo "নামজারি সম্পন্ন হলে সনদ পেতে কত দিন লাগে?" > q.txt
echo "নামজারি অনুমোদিত হলে নির্ধারিত সময়ের মধ্যে ডিসিআর/সনদ ইস্যু করা হয়।" > a.txt
python add_qna.py --q-file q.txt --a-file a.txt --category namjari --keyword "নামজারি"

# 3) Rebuild + verify
python build_data.py
node test.js            # 35 passed, 0 failed, dataset=<n>
node test_samples.js    # ALL SAMPLES PASS
python add_qna.py --check "নামজারি সম্পন্ন হলে সনদ পেতে কত দিন লাগে?"   # now answers

# 4) Optional: run the API suite
python "C:\Users\HP\AppData\Local\Temp\opencode\public_api_http_test.py"
```

If you only have a `--q`/`--a` without flags, the tool prompts for the missing
field instead of writing empty content.

### 4.4 What the tool checks before writing

- question and answer are non-empty; answer ≥ 10 chars
- the question is not a duplicate **inside the store**
- the question is not already answered by the **built dataset** (it warns, and
  needs `--force` to replace an existing exact answer)
- legacy Bengali codepoints (`U+09DF`, `U+09DD`) are canonicalised on import
  — 24% of the original corpus had them and could not be matched
- `local_qna.json` is written atomically (an interrupted run cannot truncate it)

### 4.5 Editing `local_qna.json` directly

Entry shape (only `q` and `a` required):

```json
{
  "q": "question as a user would type it",
  "a": "the answer, verbatim",
  "more": "optional alternative answer",
  "category": "khotian",
  "keyword": "খতিয়ান",
  "tpl": false,
  "note": "why this exists / who approved it — never shown to users or the API"
}
```

Then rebuild and verify as above.

### 4.6 Protecting an EXACT-match question from dedup

`qa_dedup.merge_phrasings()` collapses re-phrasings that share an answer and a
provision identity. If your new question is one of the `test_samples.js` EXACT
tier entries, also append its normalized form to `curated_labels.txt` so dedup
can never merge it away.

---

## 5. Reverting a change

```powershell
python add_qna.py --list          # find the entry number
python add_qna.py --remove 1     # delete it
python build_data.py              # rebuild without it
node test.js && node test_samples.js
```

Or, if the change is still uncommitted:

```powershell
git checkout -- data.js test_samples.js curated_labels.txt local_qna.json
```

Because `data.js` is generated and committed, you can always rebuild to the
same committed state.

---

## 5b. Running updates as a background job

`update_datasets.py` is the job for "fetch from the live API and keep the
datasets current" without human involvement:

```bash
python update_datasets.py               # refresh live Q&A + rebuild data.js + verify
python update_datasets.py --portal      # also refresh the Bhumipedia portal cache
python update_datasets.py --docs        # also rebuild docs.js (downloads act PDFs)
python update_datasets.py --no-refresh  # rebuild from caches only (offline/CI)
python update_datasets.py --no-verify   # skip the node suites
python update_datasets.py --quiet       # one line per stage, cron-friendly
```

What one run does (in order):

1. **Fetch** — re-reads `/api/v1/qna/type1/` and `/type2/` (and the portal if
   `--portal`), so questions and answers that appeared since the last run land
   automatically. Failed fetches fall back to the disk cache and still build.
2. **Build** — rebuilds `data.js` through the exact same `qa_dedup` pipeline
   `server.py` uses. The new dataset is never written over the live file.
3. **Verify** — runs `test.js` and `test_samples.js --tolerant`. The
   `--tolerant` mode means a SUGGEST-tier query that *gains* a real answer
   counts as an improvement, not a failure — that is precisely what this job
   exists to deliver.
4. **Deploy or roll back** — the current `data.js` is kept as `data.js.bak`,
   the new one is written atomically (`os.replace`), and it is only kept if
   verification passes **and** the dataset did not shrink more than 5%. Any
   failure restores `data.js.bak`, so the serving dataset is never left broken.
5. **Report** — writes `dataset_update.json` (gitignored): sizes, delta,
   per-stage durations, test results, last build log lines, timestamps. Exit
   code is `0` = deployed, `1` = rolled back / failed, `2` = bad usage.

The server picks the new `data.js` up on its next (re)start. If you want a
fresh dataset with zero downtime, restart the server right after the job:

```bash
python update_datasets.py && sudo systemctl restart bhumi-chatbot
```

Scheduling examples:

### systemd timer (Linux)

```ini
# /etc/systemd/system/bhumi-update.service
[Unit]
Description=Refresh Bhumipedia chatbot datasets from the live API

[Service]
Type=oneshot
WorkingDirectory=/opt/bhumi-chatbot
ExecStart=/usr/bin/python3 update_datasets.py --quiet
# hardest failure threshold; the job rolls back on its own
```

```ini
# /etc/systemd/system/bhumi-update.timer
[Unit]
Description=Nightly Bhumipedia dataset refresh

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bhumi-update.timer
systemctl start bhumi-update.service   # run once, right now
journalctl -u bhumi-update.service    # log of one run
```

### cron (minimal)

```cron
# every day 03:00
0 3 * * * cd /opt/bhumi-chatbot && /usr/bin/python3 update_datasets.py --quiet >> logs/update.log 2>&1
```

Alert on a non-zero exit (rollback means upstream data changed in a way that
failed verification):

```bash
0 3 * * * cd /opt/bhumi-chatbot && /usr/bin/python3 update_datasets.py --quiet || curl -fsS -m 20 'https://healthchecks.io/ping/YourUUID/fail'
```

### Windows Task Scheduler

```powershell
$action  = New-ScheduledTaskAction -Execute "python" `
             -Argument 'update_datasets.py --quiet' `
             -WorkingDirectory "C:\Users\HP\Documents\MAHMUD\Chatbot"
$trigger = New-ScheduledTaskTrigger -Daily -At 3:00AM
Register-ScheduledTask -TaskName "Bhumi dataset update" -Action $action -Trigger $trigger
```

Check the last run with `dataset_update.json` (or in PowerShell:
`Get-Content dataset_update.json | ConvertFrom-Json | Select ok,dataset_delta`).

---

## 6. Health checks and monitoring

| Endpoint | Meaning |
|---|---|
| `GET /api/health` | `{"ok": bool, "rows": {...}}` |
| `GET /api/stats` | dataset size and source row counts |
| `GET /api/search?q=...&lang=bn` | same response as the client `findAnswer()` |

`GET /api/health` returning `"ok": false` does **not** break the chatbot — it
falls back to `data.js`. Monitor it anyway so the live dataset does not rot
silently.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `test_samples.js` fails for a question you added | The new entry outranks the tier the sample expected. Move the sample to the right tier **only if the new answer is genuinely correct** (see §4.1) |
| `--check` says "question already exists" but you wanted to answer differently | Either edit the existing source entry, or `--force` the replacement |
| Bengali text looks corrupted after `add_qna.py --q ...` | On Windows, pass text via `--q-file`/`--a-file` UTF-8 files |
| Rebuild fails: "could not locate ... .sql" | The snapshot is gitignored; re-supply it. The committed `data.js` still runs |
| API mode serves nothing / `DATABASE_URL` error | Use `python server.py --sql` to run against the bundled snapshot without a database |
| You committed a change by accident | Nothing is ever auto-committed in this workflow; `git status` shows every unintended change |

---

## 8. Reference

```powershell
python update_datasets.py                # background job: refresh live API + rebuild + verify (writes dataset_update.json)
python build_data.py                     # rebuild data.js
python build_docs.py                     # rebuild docs.js (downloads act PDFs)
python api_source.py --refresh           # refresh the Q&A API cache
python add_qna.py --list                 # show hand-authored entries
python server.py --sql                   # API from the bundled snapshot
node test.js && node test_samples.js     # regressions
```

Before any deployment: `git diff --stat` and `git status` — review exactly what
changed (`data.js`, `local_qna.json`, `test_samples.js`, `curated_labels.txt`),
then commit only what is intended. Wait for the user to request the commit.