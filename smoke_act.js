// smoke_act.js - does natural user phrasing actually reach the new act entries?
const fs = require('fs'), vm = require('vm');
const sb = { module: { exports: {} }, console };
vm.createContext(sb);
vm.runInContext(
  fs.readFileSync('data.js', 'utf8') + fs.readFileSync('docs.js', 'utf8') + fs.readFileSync('app.js', 'utf8'),
  sb);
const api = sb.module.exports;
api.prepare();

const QS = [
  'AZ জোন কোনটি',
  'কৃষি অঞ্চলের কোড কত',
  'পাহাড় ও টিলা জোন কোড কী',
  'কোন অপরাধগুলো জামিনযোগ্য',
  'অনুমোদন ব্যতীত কোনো ভূমির জোন পরিবর্তন শাস্তি কত',
  'জোনিং ম্যাপ কাকে বলে',
  'বন কাকে বলে',
  'ভূমি ব্যবহার নিয়ন্ত্রণ ও কৃষিভূমি সুরক্ষা আইন ২০২৬ কত দফার',
  'এই আইন কবে কার্যকর হবে',
  'কৃষিভূমি অকৃষি কাজে ব্যবহারে সর্বোচ্চ সীমা কত শতাংশ',
  'জোনিং ম্যাপ কত বছর পরপর হালনাগাদ হয়',
  'ভূমি ব্যবহার নিয়ন্ত্রণ ও কৃষিভূমি সুরক্ষা আইনের ধারা ১৪ কী বিধান করে',
  'ধারা ১৯(২) এ কোন কোন বিষয়ে বিধি প্রণয়ন করা যাবে',
  'বিশেষ কৃষি অঞ্চলের ভূমি ক্ষতিসাধনের শাস্তি কত',
];

for (const q of QS) {
  const r = api.findAnswer(q, null, 'bn');
  console.log('Q:', q);
  if (r && r.type === 'data' && r.entry) {
    console.log('  score=' + (r.score || 0).toFixed(1) + '  matched: ' + r.entry.q.slice(0, 130));
    console.log('  A:', String(r.entry.a).slice(0, 190).replace(/\s+/g, ' '));
  } else if (r && r.type === 'small') {
    console.log('  small talk:', r.text);
  } else {
    console.log('  type=' + (r && r.type));
  }
  console.log();
}
