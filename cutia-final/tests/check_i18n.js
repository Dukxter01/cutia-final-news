// Verifică traducerile: fiecare limbă are aceleași chei ca engleza, aceleași
// locuri {} și toate topicurile din ghid. Rulat din tests/test_app.py.
const fs = require('fs');
global.I18N = {};
for (const l of process.argv.slice(2)) eval(fs.readFileSync(require('path').join(__dirname, '..', 'src', 'static', 'i18n', l + '.js'), 'utf8'));
const ref = I18N.en;
for (const l of process.argv.slice(2)) {
  const s = I18N[l];
  const missing = Object.keys(ref.strings).filter((k) => !(k in s.strings));
  const extra = Object.keys(s.strings).filter((k) => !(k in ref.strings));
  const placeholders = Object.keys(ref.strings).filter((k) => typeof ref.strings[k] === 'string' && k in s.strings
    && (ref.strings[k].match(/\{\}/g) || []).length !== (String(s.strings[k]).match(/\{\}/g) || []).length);
  const topicIssues = Object.keys(ref.topics).filter((k) => !s.topics[k] || ['title','summary','tips','prompt','pitfall'].some((f) => !s.topics[k][f]));
  console.log(l, 'strings', Object.keys(s.strings).length, '| missing', missing, '| extra', extra, '| {} mismatch', placeholders, '| topic issues', topicIssues);
  if (missing.length || extra.length || placeholders.length || topicIssues.length) process.exitCode = 1;
}
