(function () {
  "use strict";

  var BN_DIGITS = "০১২৩৪৫৬৭৮৯";

  function toBn(x) {
    return String(x).replace(/\d/g, function (d) { return BN_DIGITS[+d]; });
  }

  function bnNum(n) {
    var d = "০১২৩৪৫৬৭৮৯";
    var x = String(Math.floor(Math.max(0, Number(n) || 0)));
    var g = x.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    var o = "";
    for (var i = 0; i < g.length; i++) {
      var ch = g.charCodeAt(i);
      o += ch >= 48 && ch <= 57 ? d[ch - 48] : g[i];
    }
    return o;
  }

  function pick(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
  }

  var PUNCT = /[?।!.,;:%"'\u2018\u2019\u201c\u201d()\[\]{}<>\-_=+*\\/|~`@#$^&…]+/g;

  function norm(s) {
    return String(s)
      .toLowerCase()
      .replace(PUNCT, " ")
      .replace(/[0-9]/g, function(d) { return "০১২৩৪৫৬৭৮৯"[+d]; })
      .replace(/\u09DF/g, "\u09AF")
      .replace(/\u09BC/g, "")
      .replace(/ী/g, "ি")
      .replace(/ূ/g, "ু")
      .replace(/ষ/g, "স")
      .replace(/শ/g, "স")
      .replace(/\u09CD/g, "")
      .replace(/ভুমি/g, "জমি")
      .replace(/\s+/g, " ")
      .trim();
  }

  var STOPWORDS = {};
  ["কি", "কাকে", "বলে", "বল", "বলতে", "বলো", "বলুন", "হয", "হলো", "হবে",
   "বুঝ", "বুঝায", "বুঝে", "বোঝায", "বোঝে", "মানে", "অরথ", "কত", "কতটুকু",
   "কতটা", "কেন", "কিভাবে", "কোথায", "কোন", "কোনো", "আছে", "আছি", "ছিল",
   "জানতে", "জানি", "চাই", "চাইছি", "আমি", "আমার", "তুমি", "তোমার",
   "আপনি", "আপনার", "দাও", "দিন", "দেন", "প্লিজ", "please", "একটু", "একটা", "একটি",
   "আর", "এবং", "থেকে", "জন্য", "মধ্যে", "দিয়ে", "হলে", "করা", "করে",
   "করব", "করবো", "করবে", "করতে", "দেখতে", "লাগবে", "পারি", "পারেন", "সঙগে", "সাথে",
   "পারথকয", "বনাম", "তুলনা", "চিনতে", "জানাবেন", "জানাবো", "জানাব"
  ].forEach(function (w) { STOPWORDS[w] = true; });
  STOPWORDS["বিসতারিত"] = true;

  function tokenize(normed) {
    if (!normed) return [];
    return normed.split(" ").filter(function (t) { return t && !STOPWORDS[t]; });
  }

  function prepare() {
    DATASET.forEach(function (e) {
      e._n = norm(e.q);
      e._wn = e._n.split(" ");
      e._an = norm(e.a);
    });
    prepareDocs();
  }

  function scoreEntry(e, uN, uTs) {
    if (e._n === uN) return 1000;
    var ws = e._wn, got = 0, tot = 0;
    for (var i = 0; i < uTs.length; i++) {
      var t = uTs[i];
      if (t.length < 2) continue;
      var w = Math.pow(t.length, 1.3);
      tot += w;
      if (ws.indexOf(t) !== -1) {
        got += w;
        continue;
      }
      var fw = 0;
      for (var j = 0; j < ws.length; j++) {
        var x = ws[j];
        if (x.length >= t.length && x.indexOf(t) === 0) { fw = w * 0.85; break; }
        if (t.length >= 3 && x.length >= 3 && t.indexOf(x) === 0) { fw = w * 0.4; break; }
      }
      got += fw;
    }
    if (!tot) return 0;
    return (got / tot) * 100;
  }

  var DOC_THRESHOLD = 42;

  var CORRUPT_ALIEN_RE = /[\u0250-\u04FF\u1E00-\u1EFF£¬¢€¦§]/;
  var CORRUPT_ADJ_RE = /[\u0980-\u09FF][A-Za-z0-9]|[A-Za-z0-9][\u0980-\u09FF]/g;
  var CORRUPT_KAR_RE = /\s[েৈোৌািীুূৃ]/;

  function corruptBody(x) {
    var s = String(x).replace(/(https?:\/\/|www\.)[^\s]+/g, " ");
    if (CORRUPT_ALIEN_RE.test(s)) return true;
    if (CORRUPT_KAR_RE.test(s)) return true;
    var m = s.match(CORRUPT_ADJ_RE);
    return !!m && m.length >= 2;
  }

  function prepareDocs() {
    if (typeof DOCS === "undefined" || !DOCS || !DOCS.length) return;
    DOCS.forEach(function (d) {
      d._bad = corruptBody(d.t + "\n" + d.x);
      if (d._bad) return;
      d._n = norm(d.t);
      d._x = norm(d.x);
      d._sx = (d.sent || []).map(function (sp) {
        return norm(d.x.slice(sp[0], sp[1]));
      });
    });
  }

  function scoreDoc(d, ts) {
    var got = 0, tot = 0;
    for (var i = 0; i < ts.length; i++) {
      var t = ts[i];
      if (t.length < 3) continue;
      var w = Math.pow(t.length, 1.5);
      tot += w;
      var inBody = d._x.indexOf(t) !== -1;
      var inTitle = d._n.indexOf(t) !== -1;
      if (inBody) got += w * (inTitle ? 1.25 : 1);
      else if (inTitle) got += w;
      else {
        var p = t.slice(0, Math.min(4, t.length));
        if (p.length >= 3) {
          if (d._x.indexOf(p) !== -1) got += w * 0.45;
          else if (d._n.indexOf(p) !== -1) got += w * 0.4;
        }
      }
    }
    return tot ? (got / tot) * 100 : 0;
  }

  function bestSentence(d, ts) {
    if (!d._sx || !d._sx.length)
      return d.x.slice(0, 220);
    var bestI = 0, bestC = -1;
    for (var i = 0; i < d._sx.length; i++) {
      var c = 0;
      for (var j = 0; j < ts.length; j++)
        if (ts[j].length >= 3 && d._sx[i].indexOf(ts[j]) !== -1) c += ts[j].length;
      if (c > bestC) { bestC = c; bestI = i; }
    }
    if (bestC <= 0) bestI = 0;
    var sp = d.sent[bestI];
    var s = d.x.slice(sp[0], sp[1]);
    if (s.length > 260) s = s.slice(0, 257).replace(/\s+\S*$/, "") + "…";
    return s;
  }

  function badDocTitle(t) {
    var h = String(t).slice(0, 32);
    return /[\u0250-\u04FF\u1E00-\u1EFF]/.test(String(t).slice(0, 24)) ||
      /অমিস/.test(h) || /^পাতা\s*[০-৯0-9]+\s*\//.test(h) ||
      /\s[েৈোৌািীুূৃ]/.test(h) || /মনিটরিং সেল/.test(t) ||
      /[\u0980-\u09FF][০-৯]+\s+[A-Za-z]{2,}/.test(t);
  }

  function docLang(d) {
    return /[\u0980-\u09FF]/.test(d.t) || /[\u0980-\u09FF]/.test(d.x.slice(0, 160)) ? "bn" : "en";
  }

  function findDocs(n, ts, lang) {
    if (typeof DOCS === "undefined" || !DOCS || !DOCS.length) return [];
    var pref = lang || LANG || "bn";
    var match = [], other = [];
    for (var i = 0; i < DOCS.length; i++) {
      if (DOCS[i]._bad || badDocTitle(DOCS[i].t)) continue;
      var s = scoreDoc(DOCS[i], ts);
      if (s >= DOC_THRESHOLD)
        (docLang(DOCS[i]) === pref ? match : other)
          .push({ d: DOCS[i], s: s, quote: bestSentence(DOCS[i], ts) });
    }
    match.sort(function (a, b) { return b.s - a.s; });
    other.sort(function (a, b) { return b.s - a.s; });
    var out = match.slice(0, 2);
    if (out.length < 2 && other.length && (!match.length || match[0].s < other[0].s * 1.3))
      out.push(other[0]);
    return out;
  }

  var GREETING_RE = /(আসসালাম|অ্যাসালাম|সালাম|আদাব|নমসকার|নমসতে|হযালো|হেলো|(^| )হাই( |$)|কেমন আছ|\bhi\b|\bhello\b|\bassalam|\bas?salam\b|ualaikum)/;  var NAME_RE = /(তোমার নাম|আপনার নাম|তুমি কে|আপনি কে|আপনি কি|তুমি কি)/;
  var HELP_RE = /(সাহাযয|হেলপ|\bhelp\b|কিভাবে বযবহার|কি করতে পার|তোমার কাজ)/;
  var THANKS_RE = /(ধনযবাদ|থ্যাংক|thank)/;
  var BYE_RE = /(বিদায|টাটা|আসি|খোদা হাফেজ|\bbye\b|goodbye)/;

  var LANG_EN_RE = /(ইংরেজি|ইংরেজী|ইংলিশ|আংরেজ|\benglish\b|\binglish\b|\bangreji\b)/i;
  var LANG_BN_RE = /(বাংলা|বাঙলা|\bbangla\b|\bbangali\b|\bbengali\b)/i;
  var LANG = "bn";

  function detectLang(n) {
    var e = LANG_EN_RE.test(n), b = LANG_BN_RE.test(n);
    if (!e && !b) return null;
    if (e && b) {
      var ie = n.search(LANG_EN_RE), ib = n.search(LANG_BN_RE);
      return ie < ib ? "en" : "bn";
    }
    if (e) return "en";
    if (n.split(" ").length > 7) return null;
    return "bn";
  }

  function smallTalk(n, lang) {
    if (lang === "en") {
      if (NAME_RE.test(n))
        return pick(["I am “ভূমি বন্ধু” (Bhumi Bondhu) 🏛️ — your land-services assistant. Ask me anything about khatian, namjari, khajna, deeds and more."]);
      if (HELP_RE.test(n))
        return "I can answer land-related questions, for example:\n• What is khatian?\n• How to apply for e-namjari?\n• How to get a mouza map?\n• Land development tax payment\n\nType your question directly or tap a suggested one below. (The knowledge base answers in Bengali; English is supported for acts/documents.)";
      if (BYE_RE.test(n))
        return pick(["Goodbye! Come back anytime. 😊", "Take care! See you again."]);
      if (THANKS_RE.test(n))
        return pick(["You're welcome! Ask me anything else. 😊", "Happy to help!"]);
      if (GREETING_RE.test(n))
        return pick([
          "Hello! 🌿 What would you like to know about land services?",
          "Hi! Khatian, namjari, khajna — what can I help you with?"
        ]);
      return null;
    }
    if (NAME_RE.test(n))
      return pick(["আমি “ভূমি বন্ধু” 🏛️ — আপনার ভূমি সেবা সহকারী। খতিয়ান, নামজারি, খাজনা, দলিলসহ ভূমি সংক্রান্ত যেকোনো প্রশ্ন করুন।"]);
    if (HELP_RE.test(n))
      return "আমি ভূমি সংক্রান্ত প্রশ্নের উত্তর দিতে পারি। যেমন:\n• খতিয়ান কি?\n• নামজারি কীভাবে করব?\n• পর্চা ফি কত?\n• দলিল কত প্রকার?\n\nসরাসরি প্রশ্ন লিখুন অথবা নিচের সাজেস্টেড প্রশ্নে চাপ দিন।";
    if (BYE_RE.test(n))
      return pick(["ভালো থাকবেন! আবার আসবেন। 😊", "আল্লাহ হাফেজ! ভূমি সংক্রান্ত যেকোনো প্রশ্নে আবার জড়িয়ে পড়বেন।"]);
    if (THANKS_RE.test(n))
      return pick(["আপনাকেও ধন্যবাদ! আরও জানতে চাইলে প্রশ্ন করুন। 😊", "স্বাগতম! সবসময় পাশে আছি।"]);
    if (GREETING_RE.test(n))
      return pick([
        "ওয়ালাইকুম আসসালাম! 🌿 ভূমি সংক্রান্ত কী জানতে চান?",
        "আসসালামু আলাইকুম! খতিয়ান, নামজারি, খাজনা — কী নিয়ে জানতে চান?"
      ]);
    return null;
  }

  var THRESHOLD = 70;
  var DEFAULT_SUGGESTIONS = ["খতিয়ান কি?", "নামজারি কীভাবে করবো?", "ভূমি উন্নয়ন খাজনা আইন, ২০২৩"];
  var INTENT_RE = /(কিভাবে|কীভাবে|সময়সীমা|দিনের|\bdays?\b|ফি|\bfee\b|দণ্ড|শাস্তি|জরিমানা|\bfine\b|আবেদন|খরচ|পরিমাণ|ক্ষতিপূরণ|punish|apply)/i;
  var ABOUT_TPL_RE = /আইনটি সম্পর্কে জানতে চাই/;
  var ABOUT_INTENT_RE = /সম্পর্কে|বিষয়|পরিচিত|about\b/i;

  function isTpl(e) {
    return e.t === 1 || /অনুযায়ী|অনুযায়ি/.test(e.q) || ABOUT_TPL_RE.test(e.q);
  }

  function findAnswer(msg, lang) {
    var L = lang || LANG || "bn";
    var n = norm(msg);
    var ts = tokenize(n);
    var ranked = [];
    for (var i = 0; i < DATASET.length; i++) {
      ranked.push({ e: DATASET[i], s: scoreEntry(DATASET[i], n, ts) });
    }
    ranked.sort(function (a, b) {
      if (b.s !== a.s) return b.s - a.s;
      // tie-break: prefer the most concise question (closest lexical match)
      // so short queries like "নামজারি ফি" surface the fee amount, not a
      // long library/circular title that merely shares the same tokens.
      var la = (ts.length - a.e._wn.length);
      var lb = (ts.length - b.e._wn.length);
      var da = Math.abs(la), db = Math.abs(lb);
      if (da !== db) return da - db;
      return a.e._n.length - b.e._n.length;
    });
    var best = ranked[0];
    var st = smallTalk(n, L);
    if (st && n.split(" ").length <= 4 && !(best && best.s >= 200))
      return { type: "small", text: st };
    if (best && best.s >= THRESHOLD) {
      var raw = String(msg);
      var tpl = isTpl(best.e);
      var intentOk = tpl && ABOUT_TPL_RE.test(best.e.q)
        ? INTENT_RE.test(raw) || ABOUT_INTENT_RE.test(raw)
        : INTENT_RE.test(raw);
      if (tpl && !intentOk) {
        var alt = null;
        for (var z = 0; z < ranked.length; z++) {
          if (ranked[z].s >= THRESHOLD && !isTpl(ranked[z].e)) { alt = ranked[z]; break; }
        }
        if (alt) return { type: "data", entry: alt.e, score: alt.s };
        var dh0 = findDocs(n, ts, L);
        if (dh0.length) return { type: "doc", hits: dh0 };
      } else
        return { type: "data", entry: best.e, score: best.s };
    }

    var dh = findDocs(n, ts, L);
    if (dh.length) return { type: "doc", hits: dh };

    if (st) return { type: "small", text: st };

    var sug = [];
    for (var k = 0; k < ranked.length && sug.length < 3; k++) {
      if (ranked[k].s >= 15) sug.push(ranked[k].e.q);
    }
    if (!sug.length) sug = DEFAULT_SUGGESTIONS;
    return { type: "none", suggestions: sug };
  }

  /* ---- related questions, ranked against the dataset ------------------
     Used while the user is still typing: takes the questions closest to the
     partial text in DATASET and offers them as tappable chips above the
     input box. The single best match is surfaced first (it is the answer
     itself), followed by genuine alternatives.                               */

  var SUG_MIN_CHARS = 3;
  var SUG_MAX = 6;
  var SUG_FLOOR = 34;
  var SUG_FLOOR_ONE = 62;   // one word alone is weak evidence
  var SUG_CAND_MAX = 6000;  // bounds the worst-case scan
  var SUG_WIDE = 15000;     // a word matching more than this narrows nothing
  var SUG_DEBOUNCE = 180;
  var SUG_INDEX = null;
  // Words that carry no topical signal — probing with them would pull in
  // tens of thousands of questions ("কি" alone matches 38k) and pick an
  // arbitrary few. Skipping them keeps "ধারা" or "জমি" useful.
  var SUG_STOP = {
    "কি": 1, "কয়": 1, "এর": 1, "আইন": 1, "আইনের": 1, "আইনটি": 1, "আইনসমূহ": 1,
    "বলে": 1, "বলা": 1, "হয়েছে": 1, "হয়": 1, "চাই": 1, "জানতে": 1, "সম্পর্কে": 1,
    "সম্পর্কিত": 1, "করা": 1, "থেকে": 1, "এবং": 1, "অথবা": 1,
    "the": 1, "of": 1, "and": 1, "act": 1, "in": 1, "to": 1, "for": 1
  };

  function sugCmp(a, b) {
    if (b.s !== a.s) return b.s - a.s;
    return a.n.length - b.n.length; // prefer the most concise question
  }

  /* "ভূমি জোনিং (১)" and "ভূমি জোনিং (২)" are enumerations of one topic, so
     without this the five chips would all be the same question twice over. */
  function sugKey(q) {
    return norm(String(q).replace(/\s*\([^)]*\)/g, " ")).replace(/[\s,;:।-]+$/, "");
  }

  /* token -> entry indices, built on first use so page load is unaffected. */
  function sugIndex() {
    if (SUG_INDEX) return SUG_INDEX;
    var inv = Object.create(null);
    for (var i = 0; i < DATASET.length; i++) {
      var ws = DATASET[i]._wn;
      for (var j = 0; j < ws.length; j++) {
        var t = ws[j];
        if (t.length < 2) continue;
        var a = inv[t];
        if (a) a.push(i);
        else inv[t] = [i];
      }
    }
    SUG_INDEX = { inv: inv, keys: Object.keys(inv) };
    return SUG_INDEX;
  }

  function liveSuggest(msg) {
    var n = norm(msg);
    if (n.length < SUG_MIN_CHARS) return [];
    var ts = tokenize(n);
    if (!ts.length) return [];
    var floor = ts.length < 2 ? SUG_FLOOR_ONE : SUG_FLOOR;

    // Look the question up through the index instead of scoring all 57k
    // entries: only entries sharing a query word (or one starting with it)
    // can score above zero. Probe the most selective word first — that is
    // both faster and more precise than going by word length, and it keeps
    // a stopword-like "ধারা" (25k hits) from swamping "১৪".
    var idx = sugIndex();
    var cand = Object.create(null);
    var ncand = 0;
    var probes = [];
    for (var z = 0; z < ts.length; z++) {
      if (ts[z].length < 2 || SUG_STOP[ts[z]]) continue;
      var sz = idx.inv[ts[z]] ? idx.inv[ts[z]].length : Infinity;
      probes.push({ t: ts[z], sz: sz });
    }
    if (!probes.length) return [];
    probes.sort(function (a, b) { return a.sz - b.sz; });
    // A word covering a huge slice of the corpus ("ধারা" alone matches 25k
    // of 57k questions) points nowhere and is the most expensive thing to
    // scan, so drop it whenever a sharper word is available — that is also
    // what makes "ধারা ১৪" cheap. If nothing sharper is left, there is no
    // suggestion worth showing until the user types more.
    var sharp = probes.filter(function (x) { return x.sz <= SUG_WIDE; });
    if (!sharp.length) return [];
    probes = sharp;
    for (var p = 0; p < probes.length && ncand < SUG_CAND_MAX; p++) {
      var t = probes[p].t;
      var exact = idx.inv[t];
      if (exact) {
        for (var a = 0; a < exact.length && ncand < SUG_CAND_MAX; a++) {
          var ix = exact[a];
          if (!cand[ix]) { cand[ix] = 1; ncand++; }
        }
      }
      if (t.length >= 3 && ncand < SUG_CAND_MAX) {
        for (var q = 0; q < idx.keys.length; q++) {
          var kk = idx.keys[q];
          if (kk.length <= t.length || kk.lastIndexOf(t, 0) !== 0) continue;
          var lst = idx.inv[kk];
          for (var b = 0; b < lst.length; b++) {
            var jx = lst[b];
            if (!cand[jx]) { cand[jx] = 1; ncand++; }
          }
          if (ncand >= SUG_CAND_MAX) break;
        }
      }
    }
    if (!ncand) return [];

    var best = [];
    var seen = {};
    seen[sugKey(n)] = 1;
    for (var key in cand) {
      var e = DATASET[key];
      if (!e) continue;
      var sk = sugKey(e.q);
      if (seen[sk]) continue;
      var s = scoreEntry(e, n, ts);
      if (s < floor) continue;
      seen[sk] = 1;
      var item = { q: e.q, s: s, n: e._n };
      if (best.length < SUG_MAX) {
        best.push(item);
        if (best.length === SUG_MAX) best.sort(sugCmp);
      } else if (sugCmp(item, best[SUG_MAX - 1]) < 0) {
        // compare on the whole ordering, not just the score: a shorter
        // question must be able to displace a longer one on a score tie,
        // otherwise the first few in dataset order would win by default.
        best[SUG_MAX - 1] = item;
        best.sort(sugCmp);
      }
    }
    best.sort(sugCmp);
    if (!best.length) return [];
    // The winner is the answer's own question (e.g. typing "খতিয়ান" answers
    // "খতিয়ান কি?"), so it leads the dropdown instead of being hidden — that
    // way an exact new FAQ is always visible in the suggestions too.
    return best.map(function (x) { return x.q; });
  }

  if (typeof document === "undefined") {
function setLang(l) { LANG = l === "en" ? "en" : "bn"; }
  function getLang() { return LANG; }

  if (typeof module !== "undefined" && module.exports)
    module.exports = { norm: norm, tokenize: tokenize, prepare: prepare, findAnswer: findAnswer, liveSuggest: liveSuggest, findDocs: findDocs, toBn: toBn, detectLang: detectLang, setLang: setLang, getLang: getLang };
  else if (typeof window !== "undefined")
    window.__bhumi = { setLang: setLang, getLang: getLang };
    return;
  }

  var chatEl = document.getElementById("chat");
  var formEl = document.getElementById("form");
  var inpEl = document.getElementById("inp");
  var chipsEl = document.getElementById("chips");
  var liveSugEl = document.getElementById("liveSug");
  var statusTxt = document.getElementById("statusTxt");
  var STORE_KEY = "bhumiBondhuChat_" + DATASET.length;
  var history = [];

  var LIVE_API = String(window.__BHUMI_API__ || "").replace(/\/+$/, "");
  var LIVE_DOWN = false;

  prepare();
  var docTitles = {};
  if (typeof DOCS !== "undefined" && DOCS)
    DOCS.forEach(function (d) { docTitles[d.t] = 1; });
  var docN = Object.keys(docTitles).length;
  statusTxt.textContent = "অনলাইন • " + bnNum(DATASET.length) + "টি উত্তর" +
    (docN ? " • " + bnNum(docN) + "টি আইন/নথি" : "") + " লোড হয়েছে";

  var CHIPS = ["খতিয়ান কি?", "নামজারি কীভাবে করবো?", "মৌজা মানে কী", "ভূমি সংস্কার আইন, ২০২৩", "অর্পিত সম্পত্তি প্রত্যর্পণ আইন, ২০০১", "ভূমি উন্নয়ন খাজনা আইন, ২০২৩", "ডিক্রী বলতে কি বুঝায়?", "পার্বত্য চট্টগ্রাম ভূমি-বিরোধ নিষ্পত্তি কমিশন"];
  CHIPS.forEach(function (c) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = c;
    b.onclick = function () { send(c); };
    chipsEl.appendChild(b);
  });

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function linkify(safe) {
    return safe.replace(/(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>');
  }

  var BN_DIGITS = /^([\u09e6-\u09ef0-9]+)\.\s+/;
  var HEAD_RE = /^(ধারা|উপ-ধারা|উপধারা|অধ্যায়|ধ্যায়|দফা|একনজরে)[\s:]|^[^।\n]{2,40}\([\u09e6-\u09ef0-9]+টি\)[:]$|\*\*[^*]+\*\*[:।]\s*$/;

  function isHead(t) {
    return HEAD_RE.test(t);
  }

  function fmt(safe) {
    safe = safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    var lines = safe.split(/\n/);
    var out = [];
    var list = null;
    function closeList() {
      if (list) { out.push("</" + list + ">"); list = null; }
    }
    for (var i = 0; i < lines.length; i++) {
      var t = lines[i].trim();
      if (!t) { closeList(); continue; }
      if (/^[•\-\u2022]\s+/.test(t)) {
        if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
        out.push("<li>" + t.replace(/^[•\-\u2022]\s+/, "") + "</li>");
      } else if (BN_DIGITS.test(t)) {
        if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
        out.push("<li>" + t.replace(BN_DIGITS, "") + "</li>");
      } else {
        var cls = "";
        if (isHead(t)) cls = ' class="h"';
        else if (out.length === 0) cls = ' class="lead"';
        closeList();
        out.push("<p" + cls + ">" + t + "</p>");
      }
    }
    closeList();
    return out.join("");
  }

  function setBubble(bub, text) {
    bub.innerHTML = fmt(linkify(esc(text)));
  }

  function nowBn() {
    var d = new Date();
    var h = d.getHours(), m = d.getMinutes();
    var ap = h >= 12 ? "PM" : "AM";
    h = h % 12; if (h === 0) h = 12;
    var hh = h < 10 ? "0" + h : "" + h;
    var mm = m < 10 ? "0" + m : "" + m;
    return bnNum(hh) + ":" + bnNum(mm) + " " + ap;
  }

  function scrollDown() { chatEl.scrollTop = chatEl.scrollHeight; }

  function addMsg(role, text, time, save) {
    var wrap = document.createElement("div");
    wrap.className = "msg " + role;
    var bub = document.createElement("div");
    bub.className = "bubble";
    setBubble(bub, text);
    wrap.appendChild(bub);
    var tm = document.createElement("span");
    tm.className = "time";
    tm.textContent = time || nowBn();
    wrap.appendChild(tm);
    chatEl.appendChild(wrap);
    scrollDown();
    if (save !== false) { history.push({ role: role, text: text, time: tm.textContent }); saveHistory(); }
  }

  var typingEl = null;
  function showTyping() {
    hideTyping();
    typingEl = document.createElement("div");
    typingEl.className = "msg bot";
    typingEl.innerHTML = '<div class="typing"><i></i><i></i><i></i></div>';
    chatEl.appendChild(typingEl);
    scrollDown();
  }
  function hideTyping() {
    if (typingEl) { typingEl.remove(); typingEl = null; }
  }

  function addSuggestions(list) {
    if (!list || !list.length) return;
    var lab = document.createElement("div");
    lab.className = "suggest-label";
    lab.textContent = "আপনি কি এগুলো জানতে চান?";
    var row = document.createElement("div");
    row.className = "suggest-row";
    list.forEach(function (q) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = q;
      b.onclick = function () { row.remove(); lab.remove(); send(q); };
      row.appendChild(b);
    });
    chatEl.appendChild(lab);
    chatEl.appendChild(row);
    scrollDown();
  }

  function botReply(text, suggestions) {
    showTyping();
    var delay = 500 + Math.min(text.length * 6, 900);
    setTimeout(function () {
      hideTyping();
      addMsg("bot", text);
      addSuggestions(suggestions);
    }, delay);
  }

  function docText(hits, lang) {
    var parts = [];
    hits.forEach(function (h) {
      var d = h.d;
      var head = "📄 " + d.t.trim();
      if (d.p) head += lang === "en" ? " (p. " + d.p + ")" : " (পৃষ্ঠা " + toBn(d.p) + ")";
      parts.push(head + '\n“' + h.quote + '”' + "\n🔗 " + d.f);
    });
    return (lang === "en"
      ? "I found a match in the collected acts/documents:\n\n"
      : "আপনার প্রশ্নের সাথে মিল পেলাম সংগৃহীত আইন/নথিতে:\n\n") +
      parts.join("\n\n");
  }

  var lastUserMsg = null;
  var lastData = null;
  var MORE_RE = /(আরও|আরো|বিস্তারিত|বিশদ|ডিটেলস|details|more|সম্পূর্ণ|পুরোটা|পুরা|আর কিছু|আরো কিছু|থেকে কি হয়|তাহলে কি হবে|এরপর কি|পরের ধাপ)/;

  function respondLive(msg) {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, 4000);
    fetch(LIVE_API + "/api/search?q=" + encodeURIComponent(msg) + "&lang=" + LANG,
      { signal: ctrl.signal })
      .then(function (res) {
        if (!res.ok) throw new Error("http " + res.status);
        return res.json();
      })
      .then(function (d) {
        clearTimeout(timer);
        if (d && d.type === "data" && d.entry && d.entry.a) {
          var txt = d.entry.a;
          lastData = d.entry.more ? { q: d.entry.q, e: d.entry } : null;
          var nn = norm(msg), tts = tokenize(nn);
          var dh = findDocs(nn, tts, LANG);
          if (dh.length && dh[0].s >= 60)
            txt += "\n\n📄 " + (LANG === "en" ? "Related document" : "সম্পর্কিত নথি") + ": " + dh[0].d.t.trim() +
              "\n“" + dh[0].quote + "”" + "\n🔗 " + dh[0].d.f;
          botReply(txt);
        }
        else if (d && d.type === "small" && d.text) botReply(d.text);
        else if (d && d.type === "none" && d.suggestions && d.suggestions.length)
          botReply(LANG === "en"
            ? "Sorry, I don't have a specific answer for that. 😔\nI cover land services topics (khatian, namjari, mouza map, khajna, deeds etc.). Try rephrasing your question.\n\nOr visit https://land.gov.bd/ or call the hotline 16122 ☎️"
            : "দুঃখিত, এই বিষয়ে আমার কাছে নির্দিষ্ট উত্তর নেই। 😔\nআমি ভূমি সংক্রান্ত বিষয়ে (খতিয়ান, নামজারি, মৌজা, দাগ, খাজনা, দলিল ইত্যাদি) উত্তর দিতে পারি। অন্যভাবে প্রশ্নটি লিখে দেখুন।\n\nঅথবা ভূমি সেবা পেতে ভিজিট করুন https://land.gov.bd/ অথবা কল করুন হটলাইন ১৬১২২-এ ☎️",
            d.suggestions);
        else throw new Error("bad payload");
      })
      .catch(function () {
        clearTimeout(timer);
        LIVE_DOWN = true;
        respond(msg);
      });
  }

  function respond(msg) {
    if (LIVE_API && !LIVE_DOWN) { respondLive(msg); return; }
    var r = findAnswer(msg, LANG);
    var nn = norm(msg), tts = tokenize(nn);
    var dh = findDocs(nn, tts, LANG);
    var txt = null;

    if (MORE_RE.test(msg) && lastData && lastData.e.more && nn.split(" ").length <= 6) {
      txt = LANG === "en"
        ? "More details:\n\n" + lastData.e.more
        : "আরো বিস্তারিত:\n\n" + lastData.e.more;
      lastData = null;
      if (dh.length && dh[0].s >= 60)
        txt += "\n\n📄 " + (LANG === "en" ? "Related document" : "সম্পর্কিত নথি") + ": " + dh[0].d.t.trim() +
          "\n“" + dh[0].quote + "”" + "\n🔗 " + dh[0].d.f;
      botReply(txt);
      return;
    }

    if (r.type === "data") {
      txt = r.entry.a;
      lastData = r.entry.more ? { q: r.entry.q, e: r.entry } : null;
      if (dh.length && dh[0].s >= 60)
        txt += "\n\n📄 " + (LANG === "en" ? "Related document" : "সম্পর্কিত নথি") + ": " + dh[0].d.t.trim() +
          "\n“" + dh[0].quote + "”" + "\n🔗 " + dh[0].d.f;
      botReply(txt);
    }
    else if (r.type === "doc") botReply(docText(r.hits, LANG));
    else if (r.type === "small") botReply(r.text);
    else if (LANG === "en") botReply(
      "Sorry, I don't have a specific answer for that. 😔\nI cover land services topics (khatian, namjari, mouza map, khajna, deeds etc.). Try rephrasing your question.\n\nOr visit https://land.gov.bd/ or call the hotline 16122 ☎️",
      r.suggestions
    );
    else botReply(
      "দুঃখিত, এই বিষয়ে আমার কাছে নির্দিষ্ট উত্তর নেই। 😔\nআমি ভূমি সংক্রান্ত বিষয়ে (খতিয়ান, নামজারি, মৌজা, দাগ, খাজনা, দলিল ইত্যাদি) উত্তর দিতে পারি। অন্যভাবে প্রশ্নটি লিখে দেখুন।\n\nঅথবা ভূমি সেবা পেতে ভিজিট করুন https://land.gov.bd/ অথবা কল করুন হটলাইন ১৬১২২-এ ☎️",
      r.suggestions
    );
  }

  function send(raw) {
    var msg = String(raw || "").trim();
    if (!msg) return;
    closeLiveSug();
    inpEl.value = "";
    addMsg("user", msg);
    var lc = detectLang(norm(msg));
    if (lc && lc !== LANG) {
      LANG = lc;
      botReply(LANG === "bn"
        ? "ঠিক আছে! এখন থেকে বাংলায় উত্তর দেব। 😊"
        : "Sure! I'll reply in English from now on. 😊");
      if (lastUserMsg) {
        var prev = lastUserMsg;
        showTyping();
        setTimeout(function () { respond(prev); }, 400);
      }
      return;
    }
    lastUserMsg = msg;
    respond(msg);
  }

  function saveHistory() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(history.slice(-200))); } catch (e) {}
  }

  function loadHistory() {
    try {
      var raw = localStorage.getItem(STORE_KEY);
      if (!raw) return false;
      history = JSON.parse(raw) || [];
      history.forEach(function (m) {
        var wrap = document.createElement("div");
        wrap.className = "msg " + m.role;
        var bub = document.createElement("div");
        bub.className = "bubble";
        setBubble(bub, m.text);
        wrap.appendChild(bub);
        var tm = document.createElement("span");
        tm.className = "time";
        tm.textContent = m.time;
        wrap.appendChild(tm);
        chatEl.appendChild(wrap);
      });
      return history.length > 0;
    } catch (e) { return false; }
  }

  document.getElementById("clearBtn").onclick = function () {
    history = [];
    try { localStorage.removeItem(STORE_KEY); } catch (e) {}
    chatEl.innerHTML = "";
    welcome(true);
  };

  formEl.onsubmit = function (ev) {
    ev.preventDefault();
    send(inpEl.value);
  };

  /* ---- live question suggestions: a dropdown under the input box ------- */

  var sugTimer = null;
  var composing = false;
  var sugList = [];
  var sugSel = -1;

  function closeLiveSug() {
    if (sugTimer) { clearTimeout(sugTimer); sugTimer = null; }
    sugList = []; sugSel = -1;
    if (!liveSugEl) return;
    liveSugEl.textContent = "";
    liveSugEl.className = "live-sug";
    if (inpEl) {
      inpEl.setAttribute("aria-expanded", "false");
      inpEl.removeAttribute("aria-activedescendant");
    }
  }

  function markSug() {
    if (!liveSugEl) return;
    var items = liveSugEl.querySelectorAll("li");
    for (var i = 0; i < items.length; i++) {
      var on = i === sugSel;
      items[i].className = on ? "on" : "";
      items[i].setAttribute("aria-selected", on ? "true" : "false");
      if (on && inpEl) inpEl.setAttribute("aria-activedescendant", items[i].id);
    }
    if (sugSel >= 0 && items[sugSel] && items[sugSel].scrollIntoView)
      items[sugSel].scrollIntoView({ block: "nearest" });
  }

  function renderLiveSug(list) {
    if (!liveSugEl) return;
    if (!list || !list.length) { closeLiveSug(); return; }
    sugList = list.slice(0, SUG_MAX);
    sugSel = -1;
    liveSugEl.textContent = "";

    var lab = document.createElement("div");
    lab.className = "lab";
    lab.textContent = LANG === "en" ? "Related questions" : "সম্পর্কিত প্রশ্ন";

    var ul = document.createElement("ul");
    ul.id = "liveSugList";
    ul.setAttribute("role", "listbox");
    sugList.forEach(function (q, i) {
      var li = document.createElement("li");
      li.id = "sugOpt" + i;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      var mk = document.createElement("span");
      mk.className = "mark";
      mk.textContent = "▸";
      li.appendChild(mk);
      li.appendChild(document.createTextNode(" " + q));
      li.addEventListener("mouseenter", function () { sugSel = i; markSug(); });
      li.addEventListener("click", function () { takeSug(i); });
      ul.appendChild(li);
    });

    var foot = document.createElement("div");
    foot.className = "hintrow";
    foot.textContent = LANG === "en"
      ? "↑ ↓ choose • Enter to fill • Esc to close"
      : "↑ ↓ বাছাই • Enter দিয়ে বসান • Esc দিয়ে বন্ধ";

    liveSugEl.appendChild(lab);
    liveSugEl.appendChild(ul);
    liveSugEl.appendChild(foot);
    liveSugEl.className = "live-sug on";
    if (inpEl) {
      inpEl.setAttribute("aria-expanded", "true");
      inpEl.removeAttribute("aria-activedescendant");
    }
  }

  // Picking a suggestion fills the box rather than sending on the spot, so a
  // mis-click can still be corrected before the question is actually asked.
  function takeSug(i) {
    if (i < 0 || i >= sugList.length) return;
    var q = sugList[i];
    closeLiveSug();
    if (!inpEl) return;
    inpEl.value = q;
    inpEl.focus();
    if (inpEl.setSelectionRange) {
      try { inpEl.setSelectionRange(q.length, q.length); } catch (e) {}
    }
  }

  function moveSug(d) {
    var n = sugList.length;
    if (!n) return false;
    sugSel = sugSel < 0 ? (d > 0 ? 0 : n - 1) : (sugSel + d + n) % n;
    markSug();
    return true;
  }

  function refreshLiveSug() {
    if (sugTimer) { clearTimeout(sugTimer); sugTimer = null; }
    if (composing) return;
    var v = inpEl.value;
    if (!v || !v.trim()) { closeLiveSug(); return; }
    sugTimer = setTimeout(function () {
      sugTimer = null;
      var list = [];
      try { list = liveSuggest(v); } catch (e) { list = []; }
      renderLiveSug(list);
    }, SUG_DEBOUNCE);
  }

  if (inpEl) {
    inpEl.addEventListener("input", refreshLiveSug);

    // Bengali/Assamese input runs through an IME: never guess mid-composition.
    inpEl.addEventListener("compositionstart", function () {
      composing = true;
      closeLiveSug();
    });
    inpEl.addEventListener("compositionend", function () {
      composing = false;
      refreshLiveSug();
    });

    inpEl.addEventListener("keydown", function (ev) {
      if (composing || ev.isComposing) return;
      var k = ev.key;
      if (k === "ArrowDown" || k === "ArrowUp") {
        if (moveSug(k === "ArrowDown" ? 1 : -1)) ev.preventDefault();
        return;
      }
      if (k === "Enter") {
        // Only a highlighted row swallows Enter, so typing a full question and
        // hitting Enter still sends it instead of completing to a suggestion.
        if (sugSel >= 0) { ev.preventDefault(); takeSug(sugSel); }
        return;
      }
      if (k === "Escape") {
        if (sugList.length) { ev.preventDefault(); closeLiveSug(); }
        return;
      }
      if (k === "Tab") closeLiveSug();
    });
  }

  if (liveSugEl) {
    // The rows are not focusable, so a plain mousedown would blur the input
    // and close the list before the click landed. Swallow it to keep focus.
    liveSugEl.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
  }

  document.addEventListener("click", function (ev) {
    if (!sugList.length) return;
    if (liveSugEl && liveSugEl.contains(ev.target)) return;
    if (inpEl && inpEl.contains(ev.target)) return;
    closeLiveSug();
  });

  function welcome(force) {
    addMsg("bot",
      "আসসালামু আলাইকুম! 👋\n\n" +
      "আমি “ভূমিবিদ” — আপনার ভূমি সেবা সহকারী।\n\n" +
      "খতিয়ান, নামজারি, মৌজা, খাজনা, দলিল, জরিপ ও অধিগ্রহণসহ ভূমি-সংক্রান্ত যেকোনো বিষয়ে আপনার প্রশ্ন লিখুন — আমি প্রয়োজনীয় তথ্য ও নির্দেশনা দিয়ে সহায়তা করব।",
      null, force === true);
  }

  if (!loadHistory()) welcome(true);

  // Building the suggestion index costs ~60ms, so pay for it while the
  // browser is idle instead of on the user's first keystroke.
  if (typeof requestIdleCallback === "function") {
    requestIdleCallback(function () { try { sugIndex(); } catch (e) {} },
                        { timeout: 3000 });
  } else {
    setTimeout(function () { try { sugIndex(); } catch (e) {} }, 1200);
  }
})();
