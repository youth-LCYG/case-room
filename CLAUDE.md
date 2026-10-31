# Case Room (사건 수사실)

A bilingual (Korean/English) yes-or-no deduction game for a church youth group (grades 6–12), served by GitHub Pages at https://youth-lcyg.github.io/case-room/.

- All cases live in `cases.json`. To add or change a case, edit only that file, following `CASES.md` (content rules, Bible-case rules, picture rules).
- Run `python3 tools/validate.py` before committing; it must print OK.
- Commit to `main`. Pictures are made by hand in the Gemini app from the prompt list (each picture's `scene` plus the matching `pictureStyles` text) and saved in `images/` under the exact file names. The "Make pictures" workflow can still make missing pictures through the Cloudflare relay (secrets `RELAY_URL`, `RELAY_PASS`), but it runs only when started by hand, because pictures share the free daily Workers AI allowance with the AI judge and running out blocks the judge for about a day.
- `index.html` and `make-pictures.html` read `cases.json` at runtime; don't paste cases into them.
- A mystery may also carry `adult`: the college-group version (original lateral-thinking stories with death, suicide or crime, no gore), with its own text, `warn` content note, facts and pictures. It appears only when the page is opened with `?group=college` (a youth/college switch on the mysteries shelf; the host-screen link keeps the parameter); any other link shows the youth stories only. In the game its id is `<id>--adult`. A picture slot that names a youth slot (`"cover": "hint1"`) reuses that youth picture; a `{scene, check}` slot is a new picture saved as `images/<id>-adult-<slot>.jpg`. See `CASES.md`.
- Each case also carries `factsKo` (and `notStatedKo` for Bible cases): the same lines as `facts`/`notStated` in Korean, shown on the host screen (`index.html?host`). When you change `facts` or `notStated`, change the Korean lines to match.
- Multiplayer rooms: `rooms/worker.js` (Cloudflare Worker + Durable Object, SQLite storage) is deployed by `.github/workflows/rooms.yml` with the secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. The game connects to `ROOM_SERVER` in `index.html` (`https://case-room-rooms.youth-bf0.workers.dev`). The room owner's device runs the game and sends its state; players send intents. `qrcode.js` (MIT, vendored) draws the join QR code.
- Each rooms deploy also runs `rooms/smoke_test.py` against the live server (owner and player connect, messages both ways); the results appear as notes on the Actions run.
- To test rooms locally: run `npx wrangler dev --var ALLOWED_ORIGINS:http://127.0.0.1:8765` in `rooms/`, serve the site on port 8765, and open it with `?server=http://127.0.0.1:8787`.
- The game's owner is a youth pastor who writes in Korean. Talk with him in Korean.
