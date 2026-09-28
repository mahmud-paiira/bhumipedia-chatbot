#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Add or inspect hand-authored Q&A for the chatbot.

Bengali arguments are easiest to pass on Windows PowerShell if you put the text
in a file and use --q-file/--a-file, or edit local_qna.json by hand.

    python add_qna.py --q "question" --a "answer"
    python add_qna.py --q "question" --a "answer" --category khotian --keyword "খতিয়ান"
    python add_qna.py --q "question" --a "a1" --more "a2" --tpl
    python add_qna.py --list
    python add_qna.py --check "question to look up"
    python add_qna.py --remove 3
    python add_qna.py --q "question" --a "answer" --dry-run

The entry is appended to `local_qna.json`, which `build_db.extract_db()` reads
during every build, so the answer ends up in `data.js` and in
`/api/v1/qna/type2/` without touching the SQL dump or the live API.

`--check` is the part worth using before you write anything: it reports whether
the question already exists, and which entry wins a user's query. Adding a
question the corpus already answers is the usual way to end up with a confusing
bot, because a new low-scoring row can be outranked by a better one.
"""
import argparse
import io
import json
import os
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import local_qna as L  # noqa: E402
from qa_dedup import canonical, clean_text, norm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_dataset():
    """The rows a user's query would be matched against, right now.

    Builds from the sources so a newly added local entry is included, and falls
    back to the committed data.js when a source is unavailable (e.g. the SQL
    dump is not present on this machine).
    """
    quiet = io.StringIO()
    real, sys.stdout = sys.stdout, quiet
    try:
        from build_data import rows_from_sources
        return rows_from_sources()
    except Exception as exc:  # noqa: BLE001
        print(f"[add_qna] could not build from sources ({exc}); "
              f"using the committed data.js", file=sys.stderr)
        return _rows_from_datajs()
    finally:
        sys.stdout = real


def _rows_from_datajs():
    path = os.path.join(HERE, "data.js")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        body = f.read()
    return json.loads(body[body.index("["):body.rindex("]") + 1])


def _probe(question, rows):
    """How the chatbot would answer `question` against `rows`."""
    import scorer
    rows = scorer.prepare_dataset([dict(r) for r in rows])
    res = scorer.find_answer(question, rows)
    out = {"type": res["type"], "score": round(float(res.get("score") or 0), 1)}
    if res.get("entry"):
        out["matched_question"] = res["entry"]["q"][:90]
    if res.get("suggestions"):
        out["suggestions"] = len(res["suggestions"])
    return out


def cmd_list(args):
    entries = L.load_entries()
    if not entries:
        print("local_qna.json is empty.")
        return 0
    print(f"{len(entries)} hand-authored entries in "
          f"{os.path.basename(L.STORE)}:\n")
    for i, e in enumerate(entries, start=1):
        q = str(e.get("q", ""))
        a = str(e.get("a", ""))
        bits = []
        if e.get("category"):
            bits.append(f"category={e['category']}")
        if e.get("tpl"):
            bits.append("tpl")
        if e.get("more"):
            bits.append("more")
        tag = f"  [{', '.join(bits)}]" if bits else ""
        print(f"{i:>3}. {q[:78]}{tag}")
        print(f"     {a[:96].replace(chr(10), ' ')}")
    return 0


def cmd_check(args):
    q = clean_text(args.check)
    rows = _load_dataset()
    dups = L.find_duplicates(q, rows)
    if dups:
        print(f"question already exists ({len(dups)} exact match"
              f"{'es' if len(dups) > 1 else ''}):")
        for d in dups[:3]:
            print(f"  Q: {d['q'][:88]}")
            print(f"  A: {str(d['a'])[:110].replace(chr(10), ' ')}")
        print("\nnothing to add - edit the existing answer instead "
              "(see local_qna.json), or add a more= alternative.")
        return 1
    print("no existing entry with that exact question.")
    probe = _probe(q, rows)
    print(f"current behaviour for this query: type={probe['type']} "
          f"score={probe['score']}")
    if probe.get("matched_question"):
        print(f"  answered by: {probe['matched_question']}")
    return 0


def cmd_remove(args):
    entries = L.load_entries()
    idx = args.remove
    if idx < 1 or idx > len(entries):
        print(f"index {idx} out of range (1..{len(entries)})")
        return 1
    gone = entries.pop(idx - 1)
    L.save_entries(entries)
    print(f"removed #{idx}: {str(gone.get('q', ''))[:90]}")
    print("run: python build_data.py && node test.js && node test_samples.js")
    return 0


def cmd_add(args):
    q = clean_text(args.q)
    a = clean_text(args.a)
    more = clean_text(args.more) if args.more else None

    entries = L.load_entries()
    key = norm(q)
    for i, e in enumerate(entries, start=1):
        if norm(str(e.get("q", ""))) == key:
            print(f"already present as entry #{i}: {str(e.get('q'))[:90]}")
            print("use --remove to delete it first, or --more to add an alternative.")
            return 1

    rows = _load_dataset()
    dups = L.find_duplicates(q, rows)
    if dups:
        print(f"WARNING: the built dataset already answers this question "
              f"({len(dups)} exact match).")
        for d in dups[:2]:
            print(f"  existing Q: {d['q'][:88]}")
            print(f"  existing A: {str(d['a'])[:104].replace(chr(10), ' ')}")
        print("The new entry will win the exact match, replacing that answer.")
        if not args.force:
            print("re-run with --force to add it anyway.")

    entry = {"q": q, "a": a}
    if more:
        entry["more"] = more
    if args.category:
        entry["category"] = args.category.strip().lower()
    if args.keyword:
        entry["keyword"] = args.keyword
    if args.tpl:
        entry["tpl"] = True
    if args.note:
        entry["note"] = args.note

    candidate = entries + [entry]
    _, problems = L.validate(candidate)
    if problems:
        for p in problems:
            print(f"  {p}")
        return 1

    legacy = [c for c in (q, a, more or "") if "\u09df" in c or "\u09dd" in c]
    if legacy:
        print(f"note: legacy Bengali codepoints canonicalised on import "
              f"({len(legacy)} field(s))")

    if args.dry_run:
        print("\n--dry-run: nothing written. would add:\n")
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return 0

    L.save_entries(candidate)
    print(f"added #{len(candidate)} to {os.path.basename(L.STORE)}")
    print(f"  Q: {q[:88]}")
    print(f"  A: {a[:110].replace(chr(10), ' ')}")
    print("\nnext:")
    print("  python build_data.py            # rebuild data.js")
    print("  node test.js && node test_samples.js")
    print("  python add_qna.py --check \"" + q[:60] + "\"")
    return 0


def _prompt(field):
    """Ask for missing text interactively.

    Useful because typing Bengali into some shells is unreliable, and an empty
    or mangled question would be written straight into the dataset.
    """
    label = "question" if field == "q" else "answer"
    if not sys.stdin.isatty():
        return None
    try:
        return input(f"{label}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None


def main():
    p = argparse.ArgumentParser(
        description="Add or inspect hand-authored Q&A for the chatbot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("--q", help="the question, as a user would type it")
    p.add_argument("--q-file", help="read the question from a UTF-8 file")
    p.add_argument("--a", help="the answer, returned verbatim")
    p.add_argument("--a-file", help="read the answer from a UTF-8 file")
    p.add_argument("--more", help="an alternative answer for the same question")
    p.add_argument("--category", help="service category, e.g. khotian, namjari")
    p.add_argument("--keyword", help="short label for the entry")
    p.add_argument("--tpl", action="store_true",
                   help="mark as a statutory template answer")
    p.add_argument("--note", help="why this entry exists (never shown to users)")
    p.add_argument("--list", action="store_true", help="list stored entries")
    p.add_argument("--check", metavar="QUESTION",
                   help="does this question already exist / how is it answered?")
    p.add_argument("--remove", type=int, metavar="N", help="delete entry N")
    p.add_argument("--dry-run", action="store_true",
                   help="validate and show the entry without writing")
    p.add_argument("--force", action="store_true",
                   help="add even though the dataset already answers it")
    args = p.parse_args()

    for attr in ("q", "a"):
        fpath = getattr(args, attr + "_file", None)
        if fpath:
            with open(fpath, encoding="utf-8") as f:
                setattr(args, attr, f.read())

    # Read-only modes never need the text arguments, so they are handled first
    # and never trigger an interactive prompt.
    if args.list:
        return cmd_list(args)
    if args.remove:
        return cmd_remove(args)
    if args.check:
        return cmd_check(args)

    for attr in ("q", "a"):
        if not getattr(args, attr):
            setattr(args, attr, _prompt(attr))

    if args.q and args.a:
        return cmd_add(args)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
