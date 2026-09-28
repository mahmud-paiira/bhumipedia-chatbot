# `qna/type1` and `qna/type2` APIs

Two router-registered aliases in [`qna/urls.py`](../chatbot/qna/urls.py) that
expose the existing `QnDataViewSet` and `QAItemViewSet` under alternate
paths:

```python
router.register(r'qna/type1', QnDataViewSet, basename='qna-type1')
router.register(r'qna/type2', QAItemViewSet, basename='qna-type2')
```

Both are unauthenticated — neither view sets `permission_classes`, and the
project has no global `DEFAULT_PERMISSION_CLASSES`, so DRF falls back to
`AllowAny`.

---

## `GET /api/v1/qna/type1/`

Read-only access to the **`qnData`** table (1,065 rows).

- **View**: `qna.views.QnDataViewSet` (`ReadOnlyModelViewSet`) — only `list`
  and `retrieve`; `POST`/`PUT`/`PATCH`/`DELETE` are not allowed (405).
- **Serializer**: `QNAItemSerializer` (`fields = '__all__'`)
- **Auth**: none required
- **Ordering**: none declared — insertion order isn't guaranteed page-to-page
  (Django emits `UnorderedObjectListWarning` when paginated)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/qna/type1/` | List all qnData rows |
| GET | `/api/v1/qna/type1/<id>/` | Retrieve one row by id |

### Query params

| Param | Effect |
|---|---|
| *(none)* | Returns the full unpaginated array (all 1,065 rows) |
| `page` | Switches to paginated mode: `{count, next, previous, results}` |
| `page_size` | Rows per page when `page` is set (default 50, max 1000) |

### Row shape

```json
{
  "id": 24776,
  "question": "ডিসিআর ফি কি অনলাইনে দেয়া যাবে",
  "answer": "আপনি যদি অনলাইনে নামজারির আবেদন করে থাকেন...",
  "category": "namjari",
  "keyword": "ডিসিআর ফি"
}
```

### Example

```
GET /api/v1/qna/type1/?page=1&page_size=2
```

```json
{
  "count": 1065,
  "next": "http://.../api/v1/qna/type1/?page=2&page_size=2",
  "previous": null,
  "results": [
    { "id": 1, "question": "...", "answer": "...", "category": "...", "keyword": "..." },
    { "id": 2, "question": "...", "answer": "...", "category": "...", "keyword": "..." }
  ]
}
```

---

## `GET /api/v1/qna/type2/`

Read-only access to the **`QAItem`** table (24,995 rows). Same underlying
data as `/api/v1/items/`, but `type2` only exposes `GET` — `POST`/`PUT`/
`PATCH`/`DELETE` are not allowed here (405); use `/api/v1/items/` for
writes.

- **View**: `qna.views.QAItemReadOnlyViewSet` (`ReadOnlyModelViewSet`) — only
  `list` and `retrieve`
- **Serializer**: `QAItemSerializer` (`fields = '__all__'`)
- **Auth**: none required
- **Ordering**: none declared

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/qna/type2/` | List all QAItem rows |
| GET | `/api/v1/qna/type2/<id>/` | Retrieve one row |

### Query params

Same optional pagination as `type1`: no params → full 24,995-row array;
`?page=`/`?page_size=` → paginated.

### Row shape

```json
{
  "id": 12345,
  "question": "...",
  "answer": "...",
  "category": "...",
  "keyword": "..."
}
```

---

## Note: fixed a route collision while adding these

A plain `router.register(r'qndata', QnDataViewSet)` (added in an earlier
pass) collided with the pre-existing `controller` app's admin routes
(`qndata/add/`, `/update/`, `/delete/`, `/edit-restart/`). Because
`qna.urls` loads before `controller.urls` in the root urlconf, the router's
`qndata/<pk>/` detail pattern was treating `add`/`update`/`delete`/
`edit-restart` as a `pk` value and returning 405 instead of reaching the
real admin views. That bare registration has been removed — `qna/type1/`
gives the same read access without the collision, and the five `controller`
routes resolve correctly again.

---

## Implementation in this repository

The routes above are implemented by `public_api.py` and served by `server.py`.

```
python server.py --sql     # from the bundled .sql snapshot, no DB needed
python server.py           # from live PostgreSQL (DATABASE_URL in .env)
```

Base URLs:

| | |
|---|---|
| Live deployment | `https://bhumipedia.land.gov.bd` |
| Local (default port) | `http://127.0.0.1:8790` |

Full URL is `{base}/api/v1/qna/type1/` and `{base}/api/v1/qna/type2/`.

### Verified against the live deployment

Shapes below were probed field-by-field against `https://bhumipedia.land.gov.bd`
rather than inferred from this document:

| | live | local (`--sql`) |
|---|---|---|
| `type1` rows | 1,065 | 14,328 |
| `type2` rows | 24,995 | 48,057 |
| row keys | `id, question, answer, category, keyword` | identical |
| bare path | plain array | plain array |
| `?page=1&page_size=1` | `{count, next, previous, results}` | identical |
| rows missing `keyword` | 0 | 0 |

The local corpus is de-duplicated by `qa_dedup.py`: the iLKMS dump asks many
provisions several near-identical ways, so rows sharing one answer and one
provision identity collapse to a single label. Verified to lose **no** content
— every distinct answer and every distinct `more` payload from the 58,006-row
build is still present in the 46,745-row statutory build.

### The local corpus is now fed by the live API

`api_source.py` reads `/api/v1/qna/type1/` and `/api/v1/qna/type2/` and folds
the result into the same build, adding 1,334 curated service questions
(46,745 → 48,057). Responses are cached in `api_cache/`, so a build never
requires the host to be online; refresh with `python api_source.py --refresh`.

Three things about that upstream data are worth recording:

- **`id` is not a usable key.** `type1` and `type2` are separate tables with
  colliding id spaces, so rows are merged on normalised question text.
- **`type2` is 94% redundant** — 24,995 rows but only ~1,370 distinct
  questions, one of which appears 108 times. Duplicates collapse; a question
  that genuinely carries several distinct answers keeps the rest in `more`.
- **The table mixes questions with citizen case narratives.** Entries like
  *"আমাদের জমির সকল কাগজ সঠিক। নিয়মিত খাজনা দিয়ে আসতেছি। ভূমি দস্যুরা
  আমাদের ভূমি দখল করার কারণ…"* are individual case histories, not answerable
  knowledge. They match unrelated queries by token overlap, and including them
  made the bot answer *"জমির নিয়মিত সনদ কি?"* with a land-dispute answer at
  score 79.7 instead of offering suggestions. `api_source.is_case_narrative()`
  drops them (5,036 rows), keeping 1,334 real service questions.
- **Two Bengali letters arrive with deprecated codepoints** (`U+09DF` YYA for
  the canonical YA+NUKTA, `U+09DD` ZHA for ZZA). They affect 11,735 rows —
  including the corpus's most frequent word, `রাষ্ট্ৰীয়` (4,481 questions) —
  and hand-typed queries use the canonical spelling, so those rows could not be
  matched. `qa_dedup.canonical()` rewrites them on the way in.

### Deviations from the live deployment

1. **There are no `qnData` / `QAItem` tables in this repository.** The live
   service reads two separate tables (1,065 and 24,995 rows). This repo has
   neither; it builds one Q&A dataset of 48,057 entries from the iLKMS dump,
   the Bhumipedia portal, the PDF corpus, the local act text and the live Q&A
   API. So:
   - `type2` serves the whole dataset,
   - `type1` serves the subset whose question falls in the citizen-service
     taxonomy (`SERVICE_CATEGORIES` in `public_api.py`) — 14,328 rows.

   `id` is the 1-based position in the full dataset, so a `type1` id is also
   valid under `type2` and resolves to the same row.
2. **`category` and `keyword` are authoritative for 1,318 rows and derived for
   the rest.** Rows built from the live API carry the service's own taxonomy,
   which is passed through untouched. The remaining statutory rows have no
   label anywhere upstream, so `public_api._QNA_RULES` classifies them against
   the live category vocabulary (`khotian`, `namjari`, `khajna`, `mouja_map`,
   `dolil`, `vumi_seba`, …) and falls back to `others`.

   Guessing is measurably worse than reporting what the service said: against
   the 1,336 questions the service labels, the keyword rules agree only
   **55.8%** of the time (they mis-file `namjari` questions that merely mention
   a খতিয়ান, and `online` used to swallow every question containing
   "অনলাইন"). With the stored labels preferred, the served category matches the
   service on **1,319 of 1,319** questions present in the dataset — 100%.

   The live data's other warts — trailing spaces (`' namjari'`, `'dag '`),
   casing variants (`Khotian`, `khotIan`), and a stray `test` category — are
   normalised away here rather than reproduced. The live top category is
   `khotian`; across the whole local corpus `law` still dominates, because the
   iLKMS portion is overwhelmingly statutory text.
3. Pagination defaults (`page_size=50`, max `1000`), the `?page=`-only trigger,
   the `{"detail": "Not found."}` 404 body and the read-only surface all match.
