const fs = require("fs");
const vm = require("vm");

let code = fs.readFileSync("data.js", "utf8") + "\n";
if (fs.existsSync("docs.js")) code += fs.readFileSync("docs.js", "utf8") + "\n";
code += fs.readFileSync("app.js", "utf8");

const sandbox = { module: { exports: {} }, console };
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const datasetLen = vm.runInContext("DATASET.length", sandbox);

const api = sandbox.module.exports;
api.prepare();

const tests = [
  ["খতিয়ান কি?", "খতি"],
  ["খতিয়ান কাকে বলে", "খতি"],
  ["নামজারি কীভাবে করবো?", "নামজার"],
  ["মৌজা মানে কী", "মৌজা"],
  ["খাজনা কত?", "খাজনা"],
  ["জমি উন্নয়ন কর কি?", "উননযন"],
  ["পয়োস্তি কি?", "পযোসতির"],
  ["অর্পিত সম্পত্তি প্রত্যর্পণ আইন, ২০০১", "অরপিত সমপততি পরতযরপণ"],
  ["আসসালামু আলাইকুম", "@small"],
  ["ধন্যবাদ ভাই", "@small"],
  ["তোমার নাম কী?", "@small"],
  ["সালাম", "@small"],
  ["হেল্প দরকার", "@small"],
];

if (fs.existsSync("docs.js")) {
  tests.push(
    ["the limitation act 1908 এর বিষয় কি", "limitation act"],
    ["alluvial lands act", "alluvial lands"],
    ["public demands recovery act কী", "public demands recovery"],
    ["the state acquisition and tenancy act", "state acquisition and tenancy"],
    ["ভূমি উন্নয়ন খাজনা আইন, ২০২৩", "জমি উননযন খাজনা আইন"],
    ["মৌজা মানে কী", "মৌজা"],
    ["খতিয়ান কি?", "খতিযান"],
    ["নামজারি কীভাবে করবো?", "নামজারি"],
    ["পয়োস্তি কি?", "পযোসতির"],
    ["অর্পিত সম্পত্তি প্রত্যর্পণ আইন, ২০০১", "অরপিত সমপততি পরতযরপণ"]
  );
}

let pass = 0, fail = 0;
for (const [q, expect] of tests) {
  const r = api.findAnswer(q);
  let ok;
  if (expect === "@small") {
    ok = r.type === "small";
  } else if (expect === "@doc") {
    ok = r.type === "doc" && r.hits.length > 0;
    if (ok) console.log(`       doc: ${r.hits[0].d.t.slice(0, 60)} (p${r.hits[0].d.p}) s=${Math.round(r.hits[0].s)} | "${r.hits[0].quote.slice(0, 70)}"`);
  } else if (r.type === "data") {
    const nq = api.norm(r.entry.q);
    ok = nq.includes(expect) || r.score >= 1000;
  } else {
    ok = false;
  }
  if (ok) pass++; else fail++;
  console.log(
    (ok ? "PASS" : "FAIL") +
      ` | "${q}" -> ${r.type}${r.entry ? " score=" + Math.round(r.score) + " q=" + r.entry.q.slice(0, 40) : ""}`
  );
}

console.log("\nGibberish fallback check:");
const g1 = api.findAnswer("xyzabc blabla");
console.log(`type=${g1.type}, suggestions=${JSON.stringify(g1.suggestions)}`);
if (g1.type === "none" && g1.suggestions.length === 3) pass++; else fail++;

/* Live "related questions" shown above the input while the user types. */
console.log("\nliveSuggest checks:");
const sugTests = [
  // [typed text, how many results, substring every result must share]
  ["নামজারি ফি", 5, null],
  ["মৌজা", 5, "মৌজা"],
  ["খতিয়ান", 5, "খতিয়ান"],
  ["খাজনা", 5, "খাজনা"],
  ["xyzabc", 0, null],
  ["কি", 0, null],
  ["ধারা", 0, null],            // matches 25k questions: nothing worth showing
  ["   ", 0, null],             // whitespace
  ["ক", 0, null],               // below SUG_MIN_CHARS
];
for (const [q, want, must] of sugTests) {
  const list = api.liveSuggest(q);
  const uniq = new Set(list.map((s) => api.norm(s)));
  let ok = list.length === want && uniq.size === list.length;
  if (ok && must) ok = list.every((s) => s.includes(must));
  if (ok && want > 0) ok = !list.includes(q); // the query itself is the answer
  if (ok) pass++; else fail++;
  console.log(
    `${ok ? "PASS" : "FAIL"} | liveSuggest("${q}") -> ${list.length} hits` +
      (list.length ? ": " + list.map((s) => s.slice(0, 42)).join(" / ") : "")
  );
}

// A near-duplicate cluster such as "ভূমি জোনিং (১)/(২)/(৩)" must not fill the
// whole chip row with the same question.
const dupList = api.liveSuggest("ভূমি জোনিং");
const stems = new Set(dupList.map((s) => api.norm(s).replace(/[(]?[১-৯\d]+[)]?$/, "").trim()));
const dupOk = dupList.length > 0 && stems.size === dupList.length;
if (dupOk) pass++; else fail++;
console.log(`${dupOk ? "PASS" : "FAIL"} | no duplicate stems in liveSuggest("ভূমি জোনিং"): ${JSON.stringify(dupList)}`);

// Ranking must be stable and fast enough to run on every keystroke.
const t0 = process.hrtime.bigint();
let calls = 0;
for (let i = 0; i < 40; i++) { api.liveSuggest("নামজারি ফি কত"); calls++; }
const perCall = Number(process.hrtime.bigint() - t0) / 1e6 / calls;
const fastOk = perCall < 15;
if (fastOk) pass++; else fail++;
console.log(`${fastOk ? "PASS" : "FAIL"} | warm liveSuggest ${perCall.toFixed(2)} ms/call (budget 15ms)`);

console.log(`\n${pass} passed, ${fail} failed, dataset=${datasetLen}`);
process.exit(fail ? 1 : 0);
