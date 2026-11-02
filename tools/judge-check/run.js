// Temporary: asks the live AI judge (through the relay) a few tricky questions and compares the verdicts.
const fs = require('fs');
const tests = JSON.parse(fs.readFileSync(__dirname + '/prompts.json', 'utf8'));
const url = process.env.RELAY_URL, pass = process.env.RELAY_PASS;
const wait = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let right = 0;
  for (const t of tests) {
    let verdict = '?', raw = '';
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Passcode': pass }, body: JSON.stringify({ prompt: t.prompt, task: 'judge' }) });
        const data = await res.json().catch(() => ({}));
        raw = res.ok ? String(data.text || '') : `HTTP ${res.status} ${JSON.stringify(data)}`;
        const m = raw.match(/"verdict"\s*:\s*"([A-Z_]+)"/);
        if (m) { verdict = m[1]; break; }
        if (!res.ok && res.status !== 429 && res.status < 500) break;
      } catch (e) { raw = String(e); }
      await wait(4000);
    }
    const ok = verdict === t.want;
    if (ok) right++;
    console.log(`${ok ? 'OK  ' : 'MISS'} [${t.id}] ${t.q} -> ${verdict} (want ${t.want})${ok ? '' : ' | ' + raw.slice(0, 160)}`);
    await wait(1500);
  }
  console.log(`::notice::Judge check: ${right}/${tests.length} as expected`);
})();
