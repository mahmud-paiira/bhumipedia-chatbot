// test_samples.js — quick-sample verifier (fast sanity check after every rebuild).
// Requires: data.js, docs.js, app.js (all generated/in repo).
// Usage: node test_samples.js   (exit code 1 on any failure)
//        node test_samples.js --tolerant   # background-job mode: a SUGGEST-tier
//        query that now returns a real answer (score >= 70) counts as PASS —
//        the bot gained knowledge instead of guessing.
const fs = require('fs'), vm = require('vm');
const TOLERANT = process.argv.includes('--tolerant');

const sb = { module: { exports: {} }, console };
vm.createContext(sb);
vm.runInContext(
  fs.readFileSync('data.js', 'utf8') + fs.readFileSync('docs.js', 'utf8') + fs.readFileSync('app.js', 'utf8'),
  sb);
const api = sb.module.exports;
api.prepare();

// tier 0: must score exactly 1000 (definitive answer)
const EXACT = [
  'আইন সমূহ', 'আইন সমূহ কি কি?', 'ভূমি মন্ত্রণালয়ের আইনগুলো কি কি?', 'অধ্যাদেশসমূহ',
  'রাষ্ট্রপতির আদেশ সমূহ', 'বিধিমালা সমূহ', 'নীতিমালা সমূহ', 'পরিপত্র সমূহ কয়টি?',
  'নির্দেশিকা সমূহ', 'ম্যানুয়াল সমূহ', 'প্রজ্ঞাপন সমূহ', 'অন্যান্য সমূহ', 'সমুদয় দলিল',
  'ব্লগ সমূহ', 'ব্লগ কয়টি আছে?',
  'ফি', 'ফি সমূহ', 'বর্ণনামূলক FAQ সমূহ',
  'নামজারি ফি কত টাকা?', 'নামজারি ফি কত?', 'কোর্ট ফি কত টাকা?', 'রেকর্ড সংশোধনের ফি কত?',
  'নামজারি খতিয়ানের প্রতি কপির ফি কত?', 'নামজারি কীভাবে করবো?',
  'নামজারি করবো কিভাবে?', 'নামজারি করার ধাপগুলো কি কি?',
  'নামজারির জন্য কি কি করতে হয়?', 'নামজারি আবেদন কোথায় করতে হয়?',
  'নামজারি কি?', 'ডিসিআর কি?', 'QR কোডযুক্ত ডিসিআর কি বৈধ?',
  'ভূমি উন্নয়ন কর কি?', 'ভূমি উন্নয়ন কর কীভাবে দিবো?', 'খাজনা কি?',
  'দলিল কি?', 'দলিল কত প্রকার?', 'QR কোড দিয়ে কী যাচাই হয়?',
  'অটোমেটেড মিউটেশন সিস্টেম কি?', 'ভূমি অ্যাপ কি?',
  'ভূমি আপীল বোর্ড আইন, ১৯৮৯ এর ধারা ২ এ কী বলা হয়েছে?',
  'অর্পিত সম্পত্তি প্রত্যর্পণ আইন, ২০০১ এর ধারা ২ এ কী বলা হয়েছে?',
  'অর্পিত সম্পত্তি প্রত্যর্পণ আইন, ২০০১ এর ধারা ৪ এ কী বলা হয়েছে?',
  'স্থাবর সম্পত্তি অধিগ্রহণ ও হুকুমদখল আইন, ২০১৭ এর ধারা ৩ এ কী বলা হয়েছে?',
  'ভূমি উন্নয়ন করের হার, ২০১৫ (সংশোধনী)',
  'অটোমেটেড মিউটেশন সিস্টেম ২.১ ও মোবাইল অ্যাপ "ভূমি" উদ্বোধন',
];

// tier 1: must return a data entry at >= 70 (relevant DB text)
const CONTENT = [
  'মৌজা কি?', 'দখল কি?', 'হুকুমদখল কি?', 'খতিয়ান কি?', 'মিউটেশন কি?',
  'সায়রাত মহাল কি?',
];

// tier 2: must return suggestions (no fabricated answer)
const SUGGEST = [
  'জমির নিয়মিত সনদ কি?', 'জরিপ কত প্রকার?', 'বাংলাদেশে সর্বোচ্চ জমির মালিকানা সীমা কত একর?',
];

let fails = [];

function check(tier, q, ok, msg) {
  const tag = ok ? 'PASS' : 'FAIL';
  console.log('[' + tag + '] ' + tier.padEnd(8) + q + (ok ? '' : '  <-- ' + msg));
  if (!ok) fails.push(q + ': ' + msg);
}

for (const q of EXACT) {
  const r = api.findAnswer(q);
  const s = Math.round(r.score || 0);
  check('exact', q, s === 1000 && r.entry, 'score=' + s + ' type=' + r.type);
}
for (const q of CONTENT) {
  const r = api.findAnswer(q);
  const s = Math.round(r.score || 0);
  check('content', q, s >= 70 && r.entry, 'score=' + s + ' type=' + r.type);
}
for (const q of SUGGEST) {
  const r = api.findAnswer(q);
  const hasSug = Array.isArray(r.suggestions) && r.suggestions.length > 0 && !r.entry;
  if (TOLERANT && r.entry && (r.score || 0) >= 70) {
    console.log('[PASS] suggest ' + q + '  <-- now answered (score=' + Math.round(r.score) + ')');
    continue;
  }
  check('suggest', q, hasSug, 'type=' + r.type + ' hasEntry=' + !!r.entry);
}

console.log('\n' + (fails.length ? fails.length + ' FAILED\n' + fails.join('\n') : 'ALL SAMPLES PASS'));
process.exit(fails.length ? 1 : 0);