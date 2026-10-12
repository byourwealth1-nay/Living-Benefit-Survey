// Static GitHub Pages demo smoke check. Do not include health data or server credentials here.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync('index.html', 'utf8');
for (const text of ['Living Benefits Survey', 'consentCheck', 'stepContent', 'sideGap', 'แบบสอบถาม', 'ไม่เชื่อมต่อ Dashboard ของที่ปรึกษา']) {
  assert(html.includes(text), `Missing: ${text}`);
}
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
assert(scripts.length > 0, 'Expected inline survey app code');
for (const m of scripts) new vm.Script(m[1], { filename: 'index.html' });
console.log('Static page and embedded JavaScript passed checks');
