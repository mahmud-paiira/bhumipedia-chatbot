"""Python port of the client-side scoring used in app.js.

Keeps the live API identical to the static client: same normalization,
tokenization, scoreEntry weights, THRESHOLD, template/intent routing and
tie-breaking. Port only touches the data path (DATASET); doc search stays
in the client as an offline fallback.
"""
import re

BN_DIGITS = "০১২৩৪৫৬৭৮৯"

PUNCT = re.compile(r"""[?।!.,;:%"'""''()\[\]{}<>\-_=+*\\/|~`@#$^&…]+""")
DIGIT = re.compile(r"[0-9]")

NORM_MAP = str.maketrans({
    "\u09DF": "\u09AF",   # ৎ -> য
    "\u09BC": "",          # nukta
    "ী": "ি",
    "ূ": "ু",
    "ষ": "স",
    "শ": "স",
    "\u09CD": "",          # virama
})

STOPWORDS = {
    "কি", "কাকে", "বলে", "বল", "বলতে", "বলো", "বলুন", "হয", "হলো", "হবে",
    "বুঝ", "বুঝায", "বুঝে", "বোঝায", "বোঝে", "মানে", "অরথ", "কত", "কতটুকু",
    "কতটা", "কেন", "কিভাবে", "কোথায", "কোন", "কোনো", "আছে", "আছি", "ছিল",
    "জানতে", "জানি", "চাই", "চাইছি", "আমি", "আমার", "তুমি", "তোমার",
    "আপনি", "আপনার", "দাও", "দিন", "দেন", "প্লিজ", "please", "একটু", "একটা", "একটি",
    "আর", "এবং", "থেকে", "জন্য", "মধ্যে", "দিয়ে", "হলে", "করা", "করে",
    "করব", "করবো", "করবে", "করতে", "দেখতে", "লাগবে", "পারি", "পারেন", "সঙগে", "সাথে",
    "পারথকয", "বনাম", "তুলনা", "চিনতে", "জানাবেন", "জানাবো", "জানাব", "বিসতারিত",
}

GREETING_RE = re.compile(
    r"(আসসালাম|অ্যাসালাম|সালাম|আদাব|নমসকার|নমসতে|হযালো|হেলো|(^| )হাই( |$)|কেমন আছ|\bhi\b|\bhello\b|\bassalam|\bas?salam\b|ualaikum)")
NAME_RE = re.compile(r"(তোমার নাম|আপনার নাম|তুমি কে|আপনি কে|আপনি কি|তুমি কি)")
HELP_RE = re.compile(r"(সাহাযয|হেলপ|\bhelp\b|কিভাবে বযবহার|কি করতে পার|তোমার কাজ)")
THANKS_RE = re.compile(r"(ধনযবাদ|থ্যাংক|thank)")
BYE_RE = re.compile(r"(বিদায|টাটা|আসি|খোদা হাফেজ|\bbye\b|goodbye)")

LANG_EN_RE = re.compile(r"(ইংরেজি|ইংরেজী|ইংলিশ|আংরেজ|\benglish\b|\binglish\b|\bangreji\b)", re.I)
LANG_BN_RE = re.compile(r"(বাংলা|বাঙলা|\bbangla\b|\bbangali\b|\bbengali\b)", re.I)

THRESHOLD = 70
INTENT_RE = re.compile(
    r"(কিভাবে|কীভাবে|সময়সীমা|দিনের|\bdays?\b|ফি|\bfee\b|দণ্ড|শাস্তি|জরিমানা|\bfine\b|আবেদন|খরচ|পরিমাণ|ক্ষতিপূরণ|punish|apply)", re.I)
ABOUT_TPL_RE = re.compile(r"আইনটি সম্পর্কে জানতে চাই")
ABOUT_INTENT_RE = re.compile(r"সম্পর্কে|বিষয়|পরিচিত|about\b", re.I)
TPL_OTHER_RE = re.compile(r"অনুযায়ী|অনুযায়ি")

DEFAULT_SUGGESTIONS = ["খতিয়ান কি?", "নামজারি কীভাবে করবো?", "ভূমি উন্নয়ন খাজনা আইন, ২০২৩"]

_BNAME = ["", "এক", "দুই", "তিন", "চার", "পাঁচ", "ছয়"]


def norm(s):
    s = str(s).lower()
    s = PUNCT.sub(" ", s)
    s = DIGIT.sub(lambda m: BN_DIGITS[int(m.group(0))], s)
    s = s.translate(NORM_MAP)
    s = s.replace("ভুমি", "জমি")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokenize(normed):
    if not normed:
        return []
    return [t for t in normed.split(" ") if t and t not in STOPWORDS]


def score_entry(e, u_n, u_ts):
    """Mirror app.js scoreEntry: 1000 on exact normalized match."""
    if e["_n"] == u_n:
        return 1000.0
    ws = e["_wn"]
    got = 0.0
    tot = 0.0
    for t in u_ts:
        if len(t) < 2:
            continue
        w = len(t) ** 1.3
        tot += w
        if t in ws:
            got += w
            continue
        fw = 0.0
        for x in ws:
            if len(x) >= len(t) and x.startswith(t):
                fw = w * 0.85
                break
            if len(t) >= 3 and len(x) >= 3 and t.startswith(x):
                fw = w * 0.4
                break
        got += fw
    if not tot:
        return 0.0
    return (got / tot) * 100.0


def is_tpl(e):
    return e.get("t") == 1 or bool(TPL_OTHER_RE.search(e["q"])) or bool(ABOUT_TPL_RE.search(e["q"]))


def _rank(dataset, u_n, u_ts):
    ranked = [(e, score_entry(e, u_n, u_ts)) for e in dataset]
    ranked.sort(key=lambda it: (-it[1],
                                abs(len(u_ts) - len(it[0]["_wn"])),
                                len(it[0]["_n"])))
    return ranked


def small_talk(n, lang="bn"):
    if lang == "en":
        if NAME_RE.search(n):
            return ["I am “ভূমি বন্ধু” (Bhumi Bondhu) 🏛️ — your land-services assistant. Ask me anything about khatian, namjari, khajna, deeds and more."]
        if HELP_RE.search(n):
            return ["I can answer land-related questions, for example:\n• What is khatian?\n• How to apply for e-namjari?\n• How to get a mouza map?\n• Land development tax payment\n\nType your question directly or tap a suggested one below. (The knowledge base answers in Bengali; English is supported for acts/documents.)"]
        if BYE_RE.search(n):
            return ["Goodbye! Come back anytime. 😊", "Take care! See you again."]
        if THANKS_RE.search(n):
            return ["You're welcome! Ask me anything else. 😊", "Happy to help!"]
        if GREETING_RE.search(n):
            return ["Hello! 🌿 What would you like to know about land services?",
                    "Hi! Khatian, namjari, khajna — what can I help you with?"]
        return None
    if NAME_RE.search(n):
        return ["আমি “ভূমি বন্ধু” 🏛️ — আপনার ভূমি সেবা সহকারী। খতিয়ান, নামজারি, খাজনা, দলিলসহ ভূমি সংক্রান্ত যেকোনো প্রশ্ন করুন।"]
    if HELP_RE.search(n):
        return ["আমি ভূমি সংক্রান্ত প্রশ্নের উত্তর দিতে পারি। যেমন:\n• খতিয়ান কি?\n• নামজারি কীভাবে করব?\n• পর্চা ফি কত?\n• দলিল কত প্রকার?\n\nসরাসরি প্রশ্ন লিখুন অথবা নিচের সাজেস্টেড প্রশ্নে চাপ দিন।"]
    if BYE_RE.search(n):
        return ["ভালো থাকবেন! আবার আসবেন। 😊", "আল্লাহ হাফেজ! ভূমি সংক্রান্ত যেকোনো প্রশ্নে আবার জড়িয়ে পড়বেন।"]
    if THANKS_RE.search(n):
        return ["আপনাকেও ধন্যবাদ! আরও জানতে চাইলে প্রশ্ন করুন। 😊", "স্বাগতম! সবসময় পাশে আছি।"]
    if GREETING_RE.search(n):
        return ["ওয়ালাইকুম আসসালাম! 🌿 ভূমি সংক্রান্ত কী জানতে চান?",
                "আসসালামু আলাইকুম! খতিয়ান, নামজারি, খাজনা — কী নিয়ে জানতে চান?"]
    return None


def prepare_dataset(dataset):
    """Attach _n/_wn fields, mirroring app.js prepare() for data entries."""
    for e in dataset:
        e["_n"] = norm(e["q"])
        e["_wn"] = e["_n"].split(" ")
    return dataset


def find_answer(msg, dataset, lang="bn"):
    """Mirror app.js findAnswer for the data path.

    Returns {type, entry, score, text?, suggestions?}. Doc search is not
    ported; when a template match is blocked and no data alternate exists,
    the client falls back to its own doc search offline.
    """
    L = lang or "bn"
    n = norm(msg)
    ts = tokenize(n)
    ranked = _rank(dataset, n, ts)
    best = ranked[0]
    st = small_talk(n, L)
    if st and len(n.split(" ")) <= 4 and not (best and best[1] >= 200):
        import random
        return {"type": "small", "text": random.choice(st)}
    if best and best[1] >= THRESHOLD:
        e, s = best
        raw = str(msg)
        tpl = is_tpl(e)
        intent_ok = (tpl and ABOUT_TPL_RE.search(e["q"]) and (INTENT_RE.search(raw) or ABOUT_INTENT_RE.search(raw))) or (
            not (tpl and ABOUT_TPL_RE.search(e["q"])) and INTENT_RE.search(raw))
        if tpl and not intent_ok:
            alt = next((it for it in ranked if it[1] >= THRESHOLD and not is_tpl(it[0])), None)
            if alt:
                return {"type": "data", "entry": alt[0], "score": alt[1]}
            return {"type": "doc_blocked", "query": msg}
        return {"type": "data", "entry": e, "score": s}

    if st:
        import random
        return {"type": "small", "text": random.choice(st)}

    sug = []
    for e, s in ranked:
        if len(sug) >= 3:
            break
        if s >= 15:
            sug.append(e["q"])
    if not sug:
        sug = list(DEFAULT_SUGGESTIONS)
    return {"type": "none", "suggestions": sug}